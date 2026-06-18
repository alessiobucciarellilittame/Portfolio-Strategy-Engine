#!/usr/bin/env python3
"""
Script di esempio: costruzione core-satellite.

Confronta il profilo Bilanciato in due versioni:
(a) crypto_weight = 0% (solo core tradizionale)
(b) crypto_weight = 5% (satellite BTC)

Mostra pesi, statistiche e un mini-backtest comparativo.

Uso:
    python scripts/example_core_satellite.py
"""

import sys
import logging
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.pipeline import run_pipeline
from src.estimation import estimate_parameters
from src.profiles import load_profiles
from src.core_satellite import build_core_satellite
from src.strategies import BuyAndHold, PeriodicRebalance, simulate

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

OUTPUT_DIR = Path(__file__).parent.parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

ESTIMATION_END = date(2019, 12, 31)
SIM_START = date(2020, 1, 2)
SIM_END = date(2024, 12, 31)


def main():
    print(f"\n{'='*70}")
    print(f" CORE-SATELLITE: Bilanciato 0% vs 5% Crypto")
    print(f"{'='*70}")

    # --------------------------------------------------------
    # 1. Carica dati e stima parametri
    # --------------------------------------------------------
    print(f"\n  Caricamento dati 2015-2024...")
    bundle = run_pipeline(start=date(2015, 1, 2), end=SIM_END)
    ac_map = bundle.universe["asset_class"].to_dict()

    print(f"  Stima parametri su dati fino a {ESTIMATION_END}...")
    params = estimate_parameters(
        bundle.returns,
        mean_method="bayes_stein",
        cov_method="ledoit_wolf",
        as_of=ESTIMATION_END,
    )

    # --------------------------------------------------------
    # 2. Profilo Bilanciato
    # --------------------------------------------------------
    profiles = load_profiles()
    profile = profiles["bilanciato"]

    # --------------------------------------------------------
    # 3. Costruzione core-satellite: 0% e 5% crypto
    # --------------------------------------------------------
    print(f"\n  Costruzione portafogli...")
    r0 = build_core_satellite(
        profile, params, ac_map, crypto_weight=0.0,
    )
    r5 = build_core_satellite(
        profile, params, ac_map, crypto_weight=0.05,
    )

    # --------------------------------------------------------
    # 4. Tabella pesi
    # --------------------------------------------------------
    print(f"\n{'='*70}")
    print(f" PESI PER ASSET")
    print(f"{'='*70}")
    print(f"\n  {'Ticker':20s}  {'Classe':>10s}  {'0% crypto':>10s}  {'5% crypto':>10s}")
    print(f"  {'-'*55}")

    all_tickers = sorted(
        set(list(r0.combined_weights.keys()) + list(r5.combined_weights.keys())),
        key=lambda t: (-r5.combined_weights.get(t, 0), t),
    )
    for t in all_tickers:
        w0 = r0.combined_weights.get(t, 0)
        w5 = r5.combined_weights.get(t, 0)
        if w0 > 0.001 or w5 > 0.001:
            ac = ac_map.get(t, "?")
            print(f"  {t:20s}  {ac:>10s}  {w0:>10.2%}  {w5:>10.2%}")

    # Totali per classe
    print(f"\n  {'--- Per classe ---':20s}")
    for cls in ["equity", "bond", "commodity", "crypto"]:
        t0 = sum(w for t, w in r0.combined_weights.items() if ac_map.get(t) == cls)
        t5 = sum(w for t, w in r5.combined_weights.items() if ac_map.get(t) == cls)
        print(f"  {cls:20s}  {'':>10s}  {t0:>10.2%}  {t5:>10.2%}")

    # --------------------------------------------------------
    # 5. Tabella statistiche
    # --------------------------------------------------------
    print(f"\n{'='*70}")
    print(f" STATISTICHE ATTESE (ex-ante)")
    print(f"{'='*70}")
    print(f"\n  {'Metrica':25s}  {'0% crypto':>12s}  {'5% crypto':>12s}  {'Delta':>10s}")
    print(f"  {'-'*65}")

    for key, label in [
        ("expected_return", "Rendimento atteso"),
        ("volatility", "Volatilita'"),
        ("sharpe_ratio", "Sharpe ratio"),
        ("cvar_95", "CVaR 95%"),
    ]:
        v0 = r0.combined_stats[key]
        v5 = r5.combined_stats[key]
        delta = v5 - v0
        if key == "sharpe_ratio":
            print(f"  {label:25s}  {v0:>12.3f}  {v5:>12.3f}  {delta:>+10.3f}")
        else:
            print(f"  {label:25s}  {v0:>12.2%}  {v5:>12.2%}  {delta:>+10.2%}")

    print(f"\n  Core vol ceiling: {profile.vol_ceiling:.0%}")
    print(f"  Core vol effettiva: {r0.core_stats['volatility']:.2%}")
    print(f"  Combined vol (con 5% BTC): {r5.combined_stats['volatility']:.2%}")
    print(f"  (la vol combinata puo' superare il tetto: e' il rischio"
          f" extra della cripto)")

    # --------------------------------------------------------
    # 6. Validazione
    # --------------------------------------------------------
    print(f"\n{'='*70}")
    print(f" VALIDAZIONE")
    print(f"{'='*70}")

    for label, result in [("0% crypto", r0), ("5% crypto", r5)]:
        w_sum = sum(result.combined_weights.values())
        all_pos = all(w >= -1e-6 for w in result.combined_weights.values())
        crypto_w = sum(
            w for t, w in result.combined_weights.items()
            if ac_map.get(t) == "crypto"
        )
        core_has_crypto = any(
            ac_map.get(t) == "crypto" for t in result.core_weights
        )
        print(f"  {label}: sum={w_sum:.4f}  long_only={'OK' if all_pos else 'FAIL'}  "
              f"crypto={crypto_w:.2%}  core_no_crypto={'OK' if not core_has_crypto else 'FAIL'}")

        if result.validation_issues:
            for issue in result.validation_issues:
                print(f"    AVVISO: {issue}")

    # --------------------------------------------------------
    # 7. Mini-backtest comparativo
    # --------------------------------------------------------
    print(f"\n{'='*70}")
    print(f" MINI-BACKTEST {SIM_START} -> {SIM_END}")
    print(f"{'='*70}")

    sim_prices = bundle.prices.loc[pd.Timestamp(SIM_START):pd.Timestamp(SIM_END)]

    strat_per = PeriodicRebalance("quarterly")
    strat_bh = BuyAndHold()

    # Periodic rebalance per entrambe le versioni
    bt_0_per = simulate(
        sim_prices, r0.combined_weights, PeriodicRebalance("quarterly"),
        initial_capital=100.0, tx_cost_bps=10,
    )
    bt_5_per = simulate(
        sim_prices, r5.combined_weights, PeriodicRebalance("quarterly"),
        initial_capital=100.0, tx_cost_bps=10,
    )
    # Buy & hold per entrambe
    bt_0_bh = simulate(
        sim_prices, r0.combined_weights, BuyAndHold(),
        initial_capital=100.0, tx_cost_bps=10,
    )
    bt_5_bh = simulate(
        sim_prices, r5.combined_weights, BuyAndHold(),
        initial_capital=100.0, tx_cost_bps=10,
    )

    print(f"\n  {'Strategia':35s}  {'CAGR':>8s}  {'Vol':>8s}  {'MaxDD':>8s}  "
          f"{'Sharpe':>7s}")
    print(f"  {'-'*70}")

    all_bt = [
        ("0% crypto - Periodico (trim.)", bt_0_per),
        ("5% crypto - Periodico (trim.)", bt_5_per),
        ("0% crypto - Buy & Hold", bt_0_bh),
        ("5% crypto - Buy & Hold", bt_5_bh),
    ]

    for label, bt in all_bt:
        m = bt.metrics
        print(f"  {label:35s}  {m['cagr']:>8.2%}  {m['volatility']:>8.2%}  "
              f"{m['max_drawdown']:>8.2%}  {m['sharpe']:>7.2f}")

    # --------------------------------------------------------
    # 8. Grafico equity curves
    # --------------------------------------------------------
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(
        bt_0_per.portfolio_value.index,
        bt_0_per.portfolio_value.values,
        color="#2196F3", linewidth=1.8,
        label="0% crypto (periodico)",
    )
    ax.plot(
        bt_5_per.portfolio_value.index,
        bt_5_per.portfolio_value.values,
        color="#E91E63", linewidth=1.8,
        label="5% crypto BTC (periodico)",
    )
    ax.plot(
        bt_0_bh.portfolio_value.index,
        bt_0_bh.portfolio_value.values,
        color="#2196F3", linewidth=1.0, alpha=0.4, linestyle="--",
        label="0% crypto (B&H)",
    )
    ax.plot(
        bt_5_bh.portfolio_value.index,
        bt_5_bh.portfolio_value.values,
        color="#E91E63", linewidth=1.0, alpha=0.4, linestyle="--",
        label="5% crypto BTC (B&H)",
    )

    ax.set_xlabel("Data")
    ax.set_ylabel("Valore portafoglio (partenza = 100)")
    ax.set_title("Core-Satellite: Bilanciato 0% vs 5% Crypto (BTC)")
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(True, alpha=0.3)

    chart_path = OUTPUT_DIR / "core_satellite_equity.png"
    fig.savefig(chart_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"\n  Grafico: {chart_path}")

    print(f"\n{'='*70}\n")


if __name__ == "__main__":
    main()
