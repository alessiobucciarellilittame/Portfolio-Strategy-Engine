#!/usr/bin/env python3
"""
Script di esempio: Black-Litterman con view soggettive.

Due casi d'uso:
1. View assoluta: "EQQQ.DE rendera' l'11% annuo" (confidenza 60%)
2. View relativa: "SXR8.DE sovraperformera' EIMI.MI del 2%" (confidenza 50%)

Mostra l'effetto delle view su rendimenti attesi e allocazione.

Uso:
    python scripts/example_black_litterman.py
"""

import sys
import logging
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.pipeline import run_pipeline
from src.estimation import estimate_parameters
from src.profiles import load_profiles, build_portfolio_for_profile
from src.universe import load_universe
from src.black_litterman import (
    BLConfig,
    load_bl_config,
    run_black_litterman,
    validate_views,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def main():
    # --- Dati ---
    bundle = run_pipeline(start=date(2015, 1, 2), end=date(2024, 12, 31), use_cache=True)
    ac_map = bundle.universe["asset_class"].to_dict()

    # Stima covarianza (comune a tutti i calcoli BL)
    params = estimate_parameters(bundle.returns, cov_method="ledoit_wolf")
    tickers = list(params.tickers)
    core_tickers = [t for t in tickers if ac_map.get(t) != "crypto"]
    core_idx = [tickers.index(t) for t in core_tickers]
    core_cov = params.cov[np.ix_(core_idx, core_idx)]

    # --- Caso 0: Equilibrio (senza view) ---
    print("\n" + "=" * 70)
    print("CASO 0: EQUILIBRIO (senza view)")
    print("=" * 70)

    bl_base = load_bl_config()
    bl_base.views = []
    result_eq = run_black_litterman(core_cov, core_tickers, ac_map, bl_base)

    print(f"\nDelta calibrato: {result_eq.delta:.3f}")
    print(f"\nRendimenti impliciti Pi (excess, annui):")
    for i, t in enumerate(core_tickers):
        print(f"  {t:12s}  Pi={result_eq.pi[i]:+.2%}  mu_BL={result_eq.mu_bl[i]:.2%}")

    # --- Caso 1: View assoluta su EQQQ.DE ---
    print("\n" + "=" * 70)
    print("CASO 1: View assoluta — EQQQ.DE rendera' l'11% annuo (conf. 60%)")
    print("=" * 70)

    views_abs = [{
        "type": "absolute",
        "instrument": "EQQQ.DE",
        "expected_return": 0.11,
        "confidence": 0.60,
    }]

    errors = validate_views(views_abs, core_tickers)
    if errors:
        print(f"  ERRORI: {errors}")
        return

    bl_abs = load_bl_config()
    bl_abs.views = views_abs
    result_abs = run_black_litterman(core_cov, core_tickers, ac_map, bl_abs)

    print(f"\nRendimenti attesi (equilibrio vs con view):")
    print(f"  {'Ticker':12s}  {'Equilibrio':>10s}  {'Con view':>10s}  {'Delta':>10s}")
    for i, t in enumerate(core_tickers):
        eq = result_eq.mu_bl[i]
        post = result_abs.mu_bl[i]
        print(f"  {t:12s}  {eq:10.2%}  {post:10.2%}  {post - eq:+10.2%}")

    # Allocazione
    from src.estimation import ParameterEstimate
    profiles = load_profiles()
    profile = profiles["bilanciato"]

    for label, mu in [("Equilibrio", result_eq.mu_bl), ("Con view abs", result_abs.mu_bl)]:
        p = ParameterEstimate(
            mu=mu, cov=core_cov, tickers=core_tickers, metadata={},
        )
        pr = build_portfolio_for_profile(profile, p, horizon_years=5, asset_class_map=ac_map)
        print(f"\n  Allocazione ({label}):")
        for t, w in sorted(pr.portfolio.weights.items(), key=lambda x: -x[1]):
            if w > 0.005:
                print(f"    {t:12s}  {w:.1%}")

    # --- Caso 2: View relativa SXR8.DE > EIMI.MI ---
    print("\n" + "=" * 70)
    print("CASO 2: View relativa — SXR8.DE batte EIMI.MI del 2% (conf. 50%)")
    print("=" * 70)

    views_rel = [{
        "type": "relative",
        "long": "SXR8.DE",
        "short": "EIMI.MI",
        "outperformance": 0.02,
        "confidence": 0.50,
    }]

    errors = validate_views(views_rel, core_tickers)
    if errors:
        print(f"  ERRORI: {errors}")
        return

    bl_rel = load_bl_config()
    bl_rel.views = views_rel
    result_rel = run_black_litterman(core_cov, core_tickers, ac_map, bl_rel)

    print(f"\nRendimenti attesi (equilibrio vs con view):")
    print(f"  {'Ticker':12s}  {'Equilibrio':>10s}  {'Con view':>10s}  {'Delta':>10s}")
    for i, t in enumerate(core_tickers):
        eq = result_eq.mu_bl[i]
        post = result_rel.mu_bl[i]
        print(f"  {t:12s}  {eq:10.2%}  {post:10.2%}  {post - eq:+10.2%}")

    for label, mu in [("Equilibrio", result_eq.mu_bl), ("Con view rel", result_rel.mu_bl)]:
        p = ParameterEstimate(
            mu=mu, cov=core_cov, tickers=core_tickers, metadata={},
        )
        pr = build_portfolio_for_profile(profile, p, horizon_years=5, asset_class_map=ac_map)
        print(f"\n  Allocazione ({label}):")
        for t, w in sorted(pr.portfolio.weights.items(), key=lambda x: -x[1]):
            if w > 0.005:
                print(f"    {t:12s}  {w:.1%}")

    print("\n" + "=" * 70)
    print("DONE")
    print("=" * 70)


if __name__ == "__main__":
    main()
