#!/usr/bin/env python3
"""
Script di esempio Fase 3: ottimizzazione di portafoglio.

Uso:
    python scripts/example_optimization.py
"""

import sys
import logging
from datetime import date
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")  # Backend non interattivo
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.pipeline import run_pipeline
from src.estimation import estimate_parameters
from src.constraints import PortfolioConstraints
from src.optimizer import (
    MinVariance, MaxSharpe, MaxReturn, MinCVaR,
    validate_result,
)
from src.config import get_risk_free_rate
from src.frontier import compute_frontier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

OUTPUT_DIR = Path(__file__).parent.parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)


def print_portfolio(label: str, result, params, ac_map=None):
    """Stampa i pesi e le statistiche di un portafoglio."""
    print(f"\n  --- {label} ---")
    if not result.is_feasible():
        print(f"  INFEASIBLE: {result.metadata.get('error', result.metadata.get('status'))}")
        return

    print(f"  {'Ticker':20s}  {'Peso':>8s}  {'Classe':>10s}")
    print(f"  {'-'*42}")
    for ticker, weight in sorted(result.weights.items(), key=lambda x: -x[1]):
        ac = ac_map.get(ticker, "?") if ac_map else "?"
        if abs(weight) > 0.001:
            print(f"  {ticker:20s}  {weight:>8.2%}  {ac:>10s}")

    s = result.stats
    print(f"\n  Rendimento atteso: {s['expected_return']:>8.2%}")
    print(f"  Volatilita':       {s['volatility']:>8.2%}")
    print(f"  Sharpe ratio:      {s['sharpe_ratio']:>8.2f}")
    print(f"  CVaR 95%:          {s['cvar_95']:>8.2%}")
    print(f"  Solver status:     {result.metadata['status']}")


def main():
    print(f"\n{'='*70}")
    print(f" FASE 3 - Ottimizzazione di Portafoglio")
    print(f"{'='*70}")

    # 1. Carica dati e stima parametri
    bundle = run_pipeline(start=date(2023, 1, 2), end=date(2024, 12, 31))
    params = estimate_parameters(
        bundle.returns,
        mean_method="james_stein",
        cov_method="ledoit_wolf",
    )
    ac_map = bundle.universe["asset_class"].to_dict()

    # ============================================================
    # SANITY CHECK 1: senza vincoli, max return concentra su crypto
    # ============================================================
    print(f"\n{'='*70}")
    print(f" SANITY CHECK: Max Return SENZA vincoli")
    print(f"{'='*70}")
    print(f" (dimostra perche' servono i vincoli)")

    c_no_limits = PortfolioConstraints(long_only=True, max_weight=1.0)
    res_max_ret = MaxReturn().solve(params, c_no_limits, ac_map)
    print_portfolio("Max Return (no vincoli)", res_max_ret, params, ac_map)

    # ============================================================
    # SANITY CHECK 2: con tetto crypto, il vincolo viene rispettato
    # ============================================================
    print(f"\n{'='*70}")
    print(f" SANITY CHECK: Max Return CON tetto crypto 15%")
    print(f"{'='*70}")

    c_capped = PortfolioConstraints(
        long_only=True,
        max_weight=1.0,
        group_constraints={"crypto": (0.0, 0.15)},
    )
    res_max_ret_capped = MaxReturn().solve(params, c_capped, ac_map)
    print_portfolio("Max Return (crypto <= 15%)", res_max_ret_capped, params, ac_map)
    issues = validate_result(res_max_ret_capped, c_capped, ac_map)
    crypto_w = sum(w for t, w in res_max_ret_capped.weights.items() if ac_map.get(t) == "crypto")
    print(f"\n  Peso totale crypto: {crypto_w:.2%} (limite: 15%)")
    if issues:
        for i in issues:
            print(f"  PROBLEMA: {i}")
    else:
        print(f"  Validazione vincoli: OK")

    # ============================================================
    # Ottimizzazione con vincoli sensati
    # ============================================================
    print(f"\n{'='*70}")
    print(f" PORTAFOGLI OTTIMALI CON VINCOLI SENSATI")
    print(f" (long-only, max 15% crypto, max 25% per asset)")
    print(f"{'='*70}")

    c_sensible = PortfolioConstraints(
        long_only=True,
        max_weight=0.25,
        group_constraints={
            "crypto": (0.0, 0.15),
            "equity": (0.0, 0.70),
        },
    )

    objectives = [
        ("Minima Varianza", MinVariance()),
        ("Massimo Sharpe", MaxSharpe()),
        ("Minimo CVaR", MinCVaR(alpha=0.05)),
    ]

    for label, obj in objectives:
        result = obj.solve(params, c_sensible, ac_map)
        print_portfolio(label, result, params, ac_map)
        issues = validate_result(result, c_sensible, ac_map)
        if issues:
            for i in issues:
                print(f"  PROBLEMA: {i}")

    # ============================================================
    # SANITY CHECK 3: vol min-var <= vol equipesato
    # ============================================================
    print(f"\n{'='*70}")
    print(f" SANITY CHECK: Min Var vol <= Equipesato vol")
    print(f"{'='*70}")

    mv_result = MinVariance().solve(params, c_sensible, ac_map)
    w_eq = np.ones(params.n_assets) / params.n_assets
    vol_eq = np.sqrt(w_eq @ params.cov @ w_eq)
    print(f"  Vol Min-Variance:  {mv_result.stats['volatility']:.2%}")
    print(f"  Vol Equipesato:    {vol_eq:.2%}")
    print(f"  Check: {'OK' if mv_result.stats['volatility'] <= vol_eq + 1e-6 else 'FALLITO'}")

    # ============================================================
    # Frontiera efficiente
    # ============================================================
    print(f"\n{'='*70}")
    print(f" FRONTIERA EFFICIENTE")
    print(f"{'='*70}")

    frontier = compute_frontier(params, c_sensible, ac_map, n_points=30)
    print(f"  Punti calcolati: {frontier.n_points}")

    if frontier.n_points > 0:
        print(f"  Rendimento:  {frontier.returns.min():.2%} -> {frontier.returns.max():.2%}")
        print(f"  Volatilita': {frontier.volatilities.min():.2%} -> {frontier.volatilities.max():.2%}")

        # Grafico
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.plot(frontier.volatilities * 100, frontier.returns * 100,
                "b-", linewidth=2, label="Frontiera efficiente")

        # Portafogli speciali
        for label, obj in objectives:
            r = obj.solve(params, c_sensible, ac_map)
            if r.is_feasible():
                ax.scatter(
                    r.stats["volatility"] * 100,
                    r.stats["expected_return"] * 100,
                    s=100, zorder=5, label=label,
                )

        # Equipesato
        ret_eq = float(params.mu @ w_eq)
        ax.scatter(vol_eq * 100, ret_eq * 100, s=80, marker="^",
                   color="gray", zorder=5, label="Equipesato")

        # Singoli asset
        vols = params.volatilities()
        for i, t in enumerate(params.tickers):
            ax.scatter(vols[i] * 100, params.mu[i] * 100,
                       s=30, color="lightgray", zorder=3)
            ax.annotate(t, (vols[i] * 100, params.mu[i] * 100),
                        fontsize=7, ha="left", va="bottom")

        ax.set_xlabel("Volatilita' annualizzata (%)")
        ax.set_ylabel("Rendimento atteso annualizzato (%)")
        ax.set_title("Frontiera Efficiente (vincoli: long-only, max 15% crypto, max 25%/asset)")
        ax.legend(loc="upper left", fontsize=8)
        ax.grid(True, alpha=0.3)

        chart_path = OUTPUT_DIR / "frontiera_efficiente.png"
        fig.savefig(chart_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        print(f"\n  Grafico salvato: {chart_path}")

    print(f"\n{'='*70}\n")


if __name__ == "__main__":
    main()
