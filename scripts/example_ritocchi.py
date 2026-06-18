#!/usr/bin/env python3
"""
Script di esempio: CVaR storico vs parametrico + risk-free configurabile.

Dimostra:
1. Confronto CVaR gaussiano vs storico per portafoglio con crypto
2. Sharpe con diversi risk-free per mostrare che il parametro funziona

Uso:
    python scripts/example_ritocchi.py
"""

import sys
import logging
from datetime import date
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.pipeline import run_pipeline
from src.estimation import estimate_parameters
from src.constraints import PortfolioConstraints
from src.optimizer import (
    MinVariance, MaxReturn, MinCVaR,
    _historical_cvar, _parametric_cvar,
)
from src.config import get_risk_free_rate, set_risk_free_rate
from src.profiles import load_profiles, build_portfolio_for_profile

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


def main():
    # ============================================================
    # Carica dati
    # ============================================================
    bundle = run_pipeline(start=date(2015, 1, 2), end=date(2024, 12, 31))
    params = estimate_parameters(
        bundle.returns,
        mean_method="bayes_stein",
        cov_method="ledoit_wolf",
    )
    ac_map = bundle.universe["asset_class"].to_dict()

    # ============================================================
    # RITOCCO 1: CVaR storico vs parametrico
    # ============================================================
    print(f"\n{'='*70}")
    print(f" RITOCCO 1 — CVaR STORICO vs PARAMETRICO")
    print(f"{'='*70}")

    print(f"\n  Scenari storici disponibili: {len(params.returns)} giorni")
    print(f"  (minimo 20 per CVaR storico, abbiamo {len(params.returns)})")

    # --- Portafoglio con crypto (code grasse) ---
    c_with_crypto = PortfolioConstraints(
        long_only=True, max_weight=0.30,
        group_constraints={"crypto": (0.0, 0.15)},
    )
    # --- Portafoglio senza crypto ---
    c_no_crypto = PortfolioConstraints(
        long_only=True, max_weight=0.30,
        group_constraints={"crypto": (0.0, 0.0)},
    )

    print(f"\n  {'Portafoglio':25s}  {'CVaR storico':>13s}  {'CVaR gauss.':>12s}  "
          f"{'Diff.':>8s}  {'Metodo':>10s}")
    print(f"  {'-'*73}")

    for label, constraints in [
        ("Min Var (con crypto)", c_with_crypto),
        ("Min Var (no crypto)", c_no_crypto),
        ("Max Return (con crypto)", c_with_crypto),
        ("Min CVaR (con crypto)", c_with_crypto),
    ]:
        if "Min CVaR" in label:
            result = MinCVaR().solve(params, constraints, ac_map)
        elif "Max Return" in label:
            result = MaxReturn().solve(params, constraints, ac_map)
        else:
            result = MinVariance().solve(params, constraints, ac_map)

        if not result.is_feasible():
            print(f"  {label:25s}  INFEASIBLE")
            continue

        cvar_h = result.stats["cvar_95"]
        cvar_p = result.stats["cvar_95_parametric"]
        diff = cvar_h - cvar_p
        method = result.stats["cvar_method"]

        print(f"  {label:25s}  {cvar_h:>13.2%}  {cvar_p:>12.2%}  "
              f"{diff:>+8.2%}  {method:>10s}")

    # --- Confronto coda empirica vs gaussiana per il portafoglio con crypto ---
    print(f"\n  --- Analisi code (portafoglio con crypto, MinVar) ---")
    result = MinVariance().solve(params, c_with_crypto, ac_map)
    w = np.array([result.weights.get(t, 0.0) for t in params.tickers])
    port_daily = params.returns @ w

    alpha = 0.05
    n = len(port_daily)
    cutoff = max(1, int(np.floor(n * alpha)))
    sorted_rets = np.sort(port_daily)
    tail = sorted_rets[:cutoff]

    from scipy.stats import norm
    mu_d = float(np.mean(port_daily))
    sigma_d = float(np.std(port_daily))
    z = norm.ppf(alpha)

    print(f"\n  Rendimenti giornalieri del portafoglio:")
    print(f"    Media giornaliera:   {mu_d:.6f}")
    print(f"    Std giornaliera:     {sigma_d:.6f}")
    print(f"    Kurtosi:             {float(np.mean((port_daily - mu_d)**4) / sigma_d**4):.2f}"
          f" (normale = 3.00)")
    print(f"\n  Coda sinistra (peggiore {alpha:.0%}, {cutoff} scenari):")
    print(f"    Media coda empirica: {float(np.mean(tail)):.6f}")
    print(f"    Previsione gaussiana:{mu_d - sigma_d * norm.pdf(z) / alpha:.6f}")
    print(f"    Peggior giorno:      {float(sorted_rets[0]):.6f}")

    # Composizione crypto nel portafoglio
    crypto_w = sum(w for t, w in result.weights.items() if ac_map.get(t) == "crypto")
    print(f"\n  Peso crypto nel portafoglio: {crypto_w:.2%}")

    # ============================================================
    # RITOCCO 2: Risk-free configurabile
    # ============================================================
    print(f"\n{'='*70}")
    print(f" RITOCCO 2 — RISK-FREE CONFIGURABILE")
    print(f"{'='*70}")

    profiles = load_profiles()
    profile = profiles["bilanciato"]

    print(f"\n  Profilo: {profile.name} (vol target: {profile.vol_ceiling:.0%})")
    print(f"\n  {'Risk-free':>10s}  {'Rend. atteso':>13s}  {'Vol.':>8s}  {'Sharpe':>8s}")
    print(f"  {'-'*45}")

    for rf in [0.00, 0.01, 0.02, 0.03, 0.04, 0.05]:
        set_risk_free_rate(rf)
        result = build_portfolio_for_profile(
            profile, params, horizon_years=5, asset_class_map=ac_map,
        )
        s = result.portfolio.stats
        print(f"  {rf:>10.1%}  {s['expected_return']:>13.2%}  "
              f"{s['volatility']:>8.2%}  {s['sharpe_ratio']:>8.2f}")

    # Ripristina il default
    set_risk_free_rate(0.02)

    print(f"\n  Il portafoglio e' IDENTICO per tutti i risk-free (stessa ottimizzazione).")
    print(f"  Solo lo Sharpe cambia: (rendimento - rf) / volatilita'.")
    print(f"\n  Risk-free corrente (default): {get_risk_free_rate():.1%}")
    print(f"  Nessun valore hardcoded nel codice: unico punto di configurazione.")

    print(f"\n{'='*70}\n")


if __name__ == "__main__":
    main()
