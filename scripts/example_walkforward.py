#!/usr/bin/env python3
"""
Script di esempio Fase 6: backtest walk-forward.

Esegue il backtest walk-forward del profilo Bilanciato con
ri-stima dinamica dei parametri, e confronta con le strategie
statiche della Fase 5.

Uso:
    python scripts/example_walkforward.py
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
from src.profiles import load_profiles, build_portfolio_for_profile
from src.strategies import BuyAndHold, PeriodicRebalance, simulate
from src.walkforward import run_walkforward

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

OUTPUT_DIR = Path(__file__).parent.parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# Simulazione 2020-2024 (fuori campione)
SIM_START = date(2020, 1, 2)
SIM_END = date(2024, 12, 31)
# Per strategie statiche: stima su dati fino a fine 2019
ESTIMATION_END = date(2019, 12, 31)


def main():
    print(f"\n{'='*70}")
    print(f" FASE 6 - Backtest Walk-Forward")
    print(f"{'='*70}")

    # --------------------------------------------------------
    # 1. Carica dati
    # --------------------------------------------------------
    print(f"\n  Caricamento dati 2015-2024...")
    bundle = run_pipeline(start=date(2015, 1, 2), end=SIM_END)
    ac_map = bundle.universe["asset_class"].to_dict()

    # --------------------------------------------------------
    # 2. Profilo Bilanciato
    # --------------------------------------------------------
    profiles = load_profiles()
    profile = profiles["bilanciato"]
    print(f"\n  Profilo: {profile.name}")
    print(f"  Vol ceiling: {profile.vol_ceiling:.0%}")
    print(f"  Obiettivo: {profile.objective}")

    # --------------------------------------------------------
    # 3. Walk-forward backtest
    # --------------------------------------------------------
    print(f"\n  Walk-forward backtest...")
    print(f"    Finestra: rolling 756 giorni (~3 anni)")
    print(f"    Ribilanciamento: trimestrale")
    print(f"    Stimatori: Bayes-Stein + Ledoit-Wolf")
    print(f"    Periodo: {SIM_START} -> {SIM_END}")
    print(f"    Costi: 10 bps")

    wf_result = run_walkforward(
        prices=bundle.prices,
        returns=bundle.returns,
        profile=profile,
        asset_class_map=ac_map,
        sim_start=SIM_START,
        sim_end=SIM_END,
        frequency="quarterly",
        horizon_years=5,
        mean_method="bayes_stein",
        cov_method="ledoit_wolf",
        window_type="rolling",
        window_days=756,
        initial_capital=100.0,
        tx_cost_bps=10,
    )

    # --------------------------------------------------------
    # 4. Strategie statiche per confronto
    # --------------------------------------------------------
    print(f"\n  Strategie statiche per confronto...")
    print(f"    Stima parametri su dati fino a {ESTIMATION_END} (anti-lookahead)")

    params_static = estimate_parameters(
        bundle.returns,
        mean_method="bayes_stein",
        cov_method="ledoit_wolf",
        as_of=ESTIMATION_END,
    )

    profile_result = build_portfolio_for_profile(
        profile, params_static, horizon_years=5, asset_class_map=ac_map
    )

    if not profile_result.portfolio.is_feasible():
        print("  ERRORE: profilo statico infeasible")
        return

    static_target = profile_result.portfolio.weights
    sim_prices = bundle.prices.loc[pd.Timestamp(SIM_START):pd.Timestamp(SIM_END)]

    static_bh = simulate(
        sim_prices, static_target, BuyAndHold(),
        initial_capital=100.0, tx_cost_bps=10,
    )
    static_per = simulate(
        sim_prices, static_target, PeriodicRebalance("quarterly"),
        initial_capital=100.0, tx_cost_bps=10,
    )

    # --------------------------------------------------------
    # 5. Tabella di confronto
    # --------------------------------------------------------
    print(f"\n{'='*70}")
    print(f" CONFRONTO STRATEGIE")
    print(f"{'='*70}")
    print(f"\n  {'Strategia':30s}  {'CAGR':>8s}  {'Vol':>8s}  {'MaxDD':>8s}  "
          f"{'Sharpe':>7s}  {'N.Reb':>6s}  {'Costi':>8s}  {'Turnover':>8s}")
    print(f"  {'-'*95}")

    all_results = [
        ("Walk-Forward (dinamico)", wf_result.metrics),
        ("Statico Buy & Hold", static_bh.metrics),
        ("Statico Periodico (trim.)", static_per.metrics),
    ]

    for label, m in all_results:
        print(f"  {label:30s}  {m['cagr']:>8.2%}  {m['volatility']:>8.2%}  "
              f"{m['max_drawdown']:>8.2%}  {m['sharpe']:>7.2f}  "
              f"{m['n_rebalances']:>6d}  {m['total_costs']:>8.4f}  "
              f"{m['total_turnover']:>8.2f}")

    # --------------------------------------------------------
    # 6. Validazione
    # --------------------------------------------------------
    print(f"\n{'='*70}")
    print(f" VALIDAZIONE")
    print(f"{'='*70}")

    if wf_result.validation_warnings:
        for w in wf_result.validation_warnings:
            print(f"  AVVISO: {w}")
    else:
        print(f"  Nessun avviso di validazione")

    # Controlli standard
    w_sums = wf_result.weights_history.sum(axis=1)
    w_ok = np.allclose(w_sums, 1.0, atol=1e-3)
    pos_ok = (wf_result.weights_history.values >= -1e-4).all()
    pv_ok = (wf_result.portfolio_value > 0).all()
    print(f"\n  Walk-Forward:  pesi_sum=1: {'OK' if w_ok else 'FAIL'}  "
          f"long_only: {'OK' if pos_ok else 'FAIL'}  "
          f"PV>0: {'OK' if pv_ok else 'FAIL'}")

    # --------------------------------------------------------
    # 7. Evoluzione pesi target
    # --------------------------------------------------------
    print(f"\n{'='*70}")
    print(f" EVOLUZIONE PESI TARGET (walk-forward)")
    print(f"{'='*70}")

    tw = wf_result.target_weights_history
    if len(tw) >= 2:
        # Raggruppa per asset class
        print(f"\n  {'Data':>12s}  ", end="")
        classes = sorted(set(ac_map.values()))
        for c in classes:
            print(f"{c:>10s}  ", end="")
        print()
        print(f"  {'-'*60}")

        for i, (dt, row) in enumerate(tw.iterrows()):
            if i < 3 or i >= len(tw) - 2 or len(tw) <= 6:
                class_w = {}
                for tk, w in row.items():
                    ac = ac_map.get(tk, "?")
                    class_w[ac] = class_w.get(ac, 0) + w
                d = dt.date() if hasattr(dt, 'date') else dt
                print(f"  {str(d):>12s}  ", end="")
                for c in classes:
                    print(f"{class_w.get(c, 0):>10.1%}  ", end="")
                print()
            elif i == 3:
                print(f"  {'...':>12s}")

    # Pesi dettagliati al primo e ultimo ribilanciamento
    if len(tw) >= 2:
        for label, idx in [("Primo", 0), ("Ultimo", -1)]:
            print(f"\n  {label} ribilanciamento ({tw.index[idx].date()}):")
            row = tw.iloc[idx].sort_values(ascending=False)
            for tk, w in row.items():
                if w > 0.005:
                    print(f"    {tk:20s}  {w:.2%}  ({ac_map.get(tk, '?')})")

    # --------------------------------------------------------
    # 8. Grafico 1: Equity curves
    # --------------------------------------------------------
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(
        wf_result.portfolio_value.index,
        wf_result.portfolio_value.values,
        color="#E91E63", linewidth=2.0,
        label="Walk-Forward (dinamico)",
    )
    ax.plot(
        static_bh.portfolio_value.index,
        static_bh.portfolio_value.values,
        color="#2196F3", linewidth=1.5, alpha=0.7,
        label="Statico Buy & Hold",
    )
    ax.plot(
        static_per.portfolio_value.index,
        static_per.portfolio_value.values,
        color="#4CAF50", linewidth=1.5, alpha=0.7,
        label="Statico Periodico (trim.)",
    )

    # Segna i ribilanciamenti walk-forward
    for event in wf_result.rebalance_log[1:]:  # skip il primo (investimento)
        ax.axvline(
            pd.Timestamp(event.date), color="#E91E63",
            alpha=0.15, linewidth=0.8,
        )

    ax.set_xlabel("Data")
    ax.set_ylabel("Valore portafoglio (partenza = 100)")
    ax.set_title("Walk-Forward vs Strategie Statiche - Profilo Bilanciato")
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(True, alpha=0.3)

    chart1_path = OUTPUT_DIR / "walkforward_equity.png"
    fig.savefig(chart1_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"\n  Grafico equity curves: {chart1_path}")

    # --------------------------------------------------------
    # 9. Grafico 2: Evoluzione pesi target (area impilata)
    # --------------------------------------------------------
    if len(tw) >= 2:
        # Forward-fill a frequenza giornaliera
        tw_daily = tw.reindex(
            wf_result.portfolio_value.index, method="ffill"
        )

        # Solo asset con almeno 1% in qualche momento
        significant = tw_daily.columns[tw_daily.max() > 0.01]
        tw_plot = tw_daily[significant]

        # Ordina per peso medio decrescente
        col_order = tw_plot.mean().sort_values(ascending=False).index
        tw_plot = tw_plot[col_order]

        fig, ax = plt.subplots(figsize=(12, 6))
        colors = plt.cm.Set3(np.linspace(0, 1, len(tw_plot.columns)))
        ax.stackplot(
            tw_plot.index, tw_plot.T,
            labels=tw_plot.columns, colors=colors, alpha=0.85,
        )
        ax.set_xlabel("Data")
        ax.set_ylabel("Peso target")
        ax.set_title("Evoluzione Pesi Target - Walk-Forward Bilanciato")
        ax.legend(
            loc="center left", bbox_to_anchor=(1.01, 0.5),
            fontsize=8, framealpha=0.9,
        )
        ax.set_ylim(0, 1.0)
        ax.grid(True, alpha=0.3)

        chart2_path = OUTPUT_DIR / "walkforward_weights.png"
        fig.savefig(chart2_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        print(f"  Grafico pesi target: {chart2_path}")

    print(f"\n{'='*70}\n")


if __name__ == "__main__":
    main()
