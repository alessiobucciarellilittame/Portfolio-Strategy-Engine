#!/usr/bin/env python3
"""
Script di esempio Fase 5: strategie nel tempo.

Prende il profilo Bilanciato, calcola i pesi target, e simula
3 strategie sullo stesso periodo storico.

Uso:
    python scripts/example_strategies.py
"""

import sys
import logging
from datetime import date
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.pipeline import run_pipeline
from src.estimation import estimate_parameters
from src.profiles import load_profiles, build_portfolio_for_profile
from src.strategies import (
    BuyAndHold,
    PeriodicRebalance,
    ThresholdRebalance,
    simulate,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

OUTPUT_DIR = Path(__file__).parent.parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# Anti-lookahead: usiamo i dati fino a fine 2019 per stimare i parametri,
# poi simuliamo dal 2020 al 2024 (fuori campione)
ESTIMATION_END = date(2019, 12, 31)
SIM_START = date(2020, 1, 2)
SIM_END = date(2024, 12, 31)


def main():
    print(f"\n{'='*70}")
    print(f" FASE 5 - Strategie nel Tempo")
    print(f"{'='*70}")

    # 1. Carica dati con storia lunga
    print(f"\n  Caricamento dati 2015-2024...")
    bundle = run_pipeline(start=date(2015, 1, 2), end=SIM_END)
    ac_map = bundle.universe["asset_class"].to_dict()

    # 2. Stima parametri solo sui dati fino a ESTIMATION_END (anti-lookahead)
    print(f"\n  Stima parametri su dati fino a {ESTIMATION_END} (anti-lookahead)...")
    params = estimate_parameters(
        bundle.returns,
        mean_method="bayes_stein",
        cov_method="ledoit_wolf",
        as_of=ESTIMATION_END,
    )

    # 3. Calcola pesi target con profilo Bilanciato
    profiles = load_profiles()
    profile_result = build_portfolio_for_profile(
        profiles["bilanciato"], params, horizon_years=5, asset_class_map=ac_map
    )

    if not profile_result.portfolio.is_feasible():
        print("  ERRORE: profilo infeasible")
        return

    target_weights = profile_result.portfolio.weights
    print(f"\n  Profilo: {profile_result.profile_name}")
    print(f"  Pesi target:")
    for t, w in sorted(target_weights.items(), key=lambda x: -x[1]):
        if w > 0.005:
            print(f"    {t:20s}  {w:.2%}")

    # 4. Prepara i prezzi per la simulazione (solo periodo fuori campione)
    sim_prices = bundle.prices.loc[SIM_START:SIM_END]
    print(f"\n  Periodo simulazione: {sim_prices.index[0].date()} -> "
          f"{sim_prices.index[-1].date()} ({len(sim_prices)} giorni)")

    # 5. Simula le 3 strategie
    strategies = [
        ("Buy & Hold",              BuyAndHold()),
        ("Periodico (trimestrale)", PeriodicRebalance("quarterly")),
        ("A soglia (±5pp)",         ThresholdRebalance(threshold=0.05)),
    ]

    results = {}
    for label, strategy in strategies:
        result = simulate(
            sim_prices, target_weights, strategy,
            initial_capital=100.0, tx_cost_bps=10,
        )
        results[label] = result

    # 6. Tabella comparativa
    print(f"\n{'='*70}")
    print(f" CONFRONTO STRATEGIE")
    print(f"{'='*70}")
    print(f"\n  {'Strategia':30s}  {'CAGR':>8s}  {'Vol':>8s}  {'MaxDD':>8s}  "
          f"{'Sharpe':>7s}  {'N.Reb':>6s}  {'Costi':>8s}  {'Turnover':>8s}")
    print(f"  {'-'*95}")

    for label, result in results.items():
        m = result.metrics
        print(f"  {label:30s}  {m['cagr']:>8.2%}  {m['volatility']:>8.2%}  "
              f"{m['max_drawdown']:>8.2%}  {m['sharpe']:>7.2f}  "
              f"{m['n_rebalances']:>6d}  {m['total_costs']:>8.4f}  "
              f"{m['total_turnover']:>8.2f}")

    # 7. Dettaglio ribilanciamenti
    print(f"\n{'='*70}")
    print(f" DETTAGLIO RIBILANCIAMENTI")
    print(f"{'='*70}")
    for label, result in results.items():
        n = result.metrics["n_rebalances"]
        costs = result.metrics["total_costs"]
        print(f"\n  {label}:")
        print(f"    Ribilanciamenti: {n}")
        print(f"    Costi totali: {costs:.4f} (su capitale iniziale 100)")
        if n > 0 and n <= 5:
            for e in result.rebalance_log:
                print(f"      {e.date}: turnover={e.turnover:.4f}, costo={e.cost:.4f}")
        elif n > 5:
            # Primi e ultimi
            for e in result.rebalance_log[:2]:
                print(f"      {e.date}: turnover={e.turnover:.4f}, costo={e.cost:.4f}")
            print(f"      ... ({n-4} intermedi) ...")
            for e in result.rebalance_log[-2:]:
                print(f"      {e.date}: turnover={e.turnover:.4f}, costo={e.cost:.4f}")

    # 8. Validazioni
    print(f"\n{'='*70}")
    print(f" VALIDAZIONE")
    print(f"{'='*70}")
    for label, result in results.items():
        w_sums = result.weights_history.sum(axis=1)
        w_ok = np.allclose(w_sums, 1.0, atol=1e-3)
        pos_ok = (result.weights_history.values >= -1e-4).all()
        pv_ok = (result.portfolio_value > 0).all()
        print(f"  {label:30s}  pesi_sum=1: {'OK' if w_ok else 'FAIL'}  "
              f"long_only: {'OK' if pos_ok else 'FAIL'}  "
              f"PV>0: {'OK' if pv_ok else 'FAIL'}")

    # 9. Grafico equity curves
    fig, ax = plt.subplots(figsize=(12, 6))
    colors = ["#2196F3", "#F44336", "#4CAF50"]

    for (label, result), color in zip(results.items(), colors):
        pv = result.portfolio_value
        ax.plot(pv.index, pv.values, color=color, linewidth=1.5, label=label)

    ax.set_xlabel("Data")
    ax.set_ylabel("Valore portafoglio (partenza = 100)")
    ax.set_title("Equity Curves - Profilo Bilanciato (3 strategie)")
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(True, alpha=0.3)

    chart_path = OUTPUT_DIR / "equity_curves.png"
    fig.savefig(chart_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"\n  Grafico salvato: {chart_path}")

    print(f"\n{'='*70}\n")


if __name__ == "__main__":
    main()
