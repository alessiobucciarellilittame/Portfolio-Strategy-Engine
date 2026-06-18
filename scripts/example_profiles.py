#!/usr/bin/env python3
"""
Script di esempio: profilazione cliente con vol ceiling come leva primaria.

Mostra tutti e 5 i profili con:
- Target di volatilita' vs vol realizzata (devono coincidere)
- Composizione per classe (equity guidata dal vol ceiling, non da tetti)
- Grafico rischio/rendimento sulla frontiera efficiente

Uso:
    python scripts/example_profiles.py
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
from src.profiles import (
    build_all_profiles,
    validate_monotonicity,
    PROFILE_ORDER,
)
from src.frontier import compute_frontier
from src.constraints import PortfolioConstraints

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

OUTPUT_DIR = Path(__file__).parent.parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

HORIZON_YEARS = 5  # Orizzonte di default


def main():
    print(f"\n{'='*70}")
    print(f" PROFILAZIONE CLIENTE - Vol Ceiling come Leva Primaria")
    print(f"{'='*70}")

    # 1. Carica dati
    print(f"\n  Caricamento dati 2015-2024...")
    bundle = run_pipeline(start=date(2015, 1, 2), end=date(2024, 12, 31))

    # 2. Stima parametri (Bayes-Stein + Ledoit-Wolf)
    print(f"  Stima parametri...")
    params = estimate_parameters(
        bundle.returns,
        mean_method="bayes_stein",
        cov_method="ledoit_wolf",
    )
    ac_map = bundle.universe["asset_class"].to_dict()

    # 3. Costruisci portafogli per tutti i profili
    results = build_all_profiles(
        params,
        horizon_years=HORIZON_YEARS,
        asset_class_map=ac_map,
    )

    # --------------------------------------------------------
    # 4. Tabella: Target vs Realizzato
    # --------------------------------------------------------
    print(f"\n{'='*70}")
    print(f" TARGET vs REALIZZATO (orizzonte: {HORIZON_YEARS} anni)")
    print(f"{'='*70}")

    print(f"\n  {'Profilo':15s}  {'Vol Target':>10s}  {'Vol Reale':>10s}  "
          f"{'Delta':>8s}  {'Rend.':>8s}  {'Sharpe':>7s}  {'OK':>4s}")
    print(f"  {'-'*72}")

    for r in results:
        s = r.portfolio.stats
        target = r.effective_vol_ceiling
        vol = s["volatility"]
        delta = vol - target if target else 0
        hit = abs(delta) < 0.005  # entro 0.5pp
        feas = r.portfolio.is_feasible()
        print(f"  {r.profile_name:15s}  {target:>10.2%}  {vol:>10.2%}  "
              f"{delta:>+8.2%}  {s['expected_return']:>8.2%}  "
              f"{s['sharpe_ratio']:>7.2f}  {'Y' if hit and feas else 'N':>4s}")

    # --------------------------------------------------------
    # 5. Composizione per classe
    # --------------------------------------------------------
    print(f"\n{'='*70}")
    print(f" COMPOSIZIONE PER CLASSE")
    print(f"{'='*70}")

    classes = ["equity", "bond", "commodity", "crypto"]
    print(f"\n  {'Profilo':15s}", end="")
    for cls in classes:
        print(f"  {cls:>10s}", end="")
    print()
    print(f"  {'-'*60}")

    for r in results:
        if not r.portfolio.is_feasible():
            continue
        class_w: dict[str, float] = {}
        for t, w in r.portfolio.weights.items():
            ac = ac_map.get(t, "?")
            class_w[ac] = class_w.get(ac, 0) + w
        print(f"  {r.profile_name:15s}", end="")
        for cls in classes:
            print(f"  {class_w.get(cls, 0):>10.1%}", end="")
        print()

    # --------------------------------------------------------
    # 6. Pesi dettagliati per profilo
    # --------------------------------------------------------
    print(f"\n{'='*70}")
    print(f" PESI DETTAGLIATI")
    print(f"{'='*70}")

    for r in results:
        print(f"\n  --- {r.profile_name.upper()} "
              f"(vol target={r.effective_vol_ceiling:.0%}) ---")
        if not r.portfolio.is_feasible():
            print(f"  INFEASIBLE")
            continue

        print(f"  {'Ticker':20s}  {'Peso':>8s}  {'Classe':>10s}")
        for t, w in sorted(r.portfolio.weights.items(), key=lambda x: -x[1]):
            if abs(w) > 0.005:
                print(f"  {t:20s}  {w:>8.2%}  {ac_map.get(t, '?'):>10s}")

    # --------------------------------------------------------
    # 7. Validazione
    # --------------------------------------------------------
    print(f"\n{'='*70}")
    print(f" VALIDAZIONE")
    print(f"{'='*70}")

    mono_issues = validate_monotonicity(results)
    if mono_issues:
        for issue in mono_issues:
            print(f"  PROBLEMA: {issue}")
    else:
        print(f"  Monotonicita' rischio tra profili: OK")

    for r in results:
        if r.validation_issues:
            for issue in r.validation_issues:
                print(f"  {r.profile_name}: {issue}")
        else:
            print(f"  {r.profile_name}: vincoli OK")

    # --------------------------------------------------------
    # 8. Effetto orizzonte (bilanciato)
    # --------------------------------------------------------
    print(f"\n{'='*70}")
    print(f" EFFETTO ORIZZONTE (profilo bilanciato)")
    print(f"{'='*70}")

    from src.profiles import load_profiles, build_portfolio_for_profile
    profiles = load_profiles()
    for h in [2, 5, 10]:
        rh = build_portfolio_for_profile(
            profiles["bilanciato"], params, horizon_years=h, asset_class_map=ac_map
        )
        s = rh.portfolio.stats
        vc = f"{rh.effective_vol_ceiling:.1%}" if rh.effective_vol_ceiling else "n/a"
        print(f"  Orizzonte {h:2d}y ({rh.horizon_band:6s}): "
              f"vol={s['volatility']:.2%}, rend={s['expected_return']:.2%}, "
              f"vol_ceil={vc}")

    # --------------------------------------------------------
    # 9. Grafico: profili sulla frontiera efficiente
    # --------------------------------------------------------
    print(f"\n  Calcolo frontiera efficiente...")

    # Frontiera senza crypto (core tradizionale)
    from src.estimation import filter_params, get_crypto_tickers
    crypto_set = get_crypto_tickers(params.tickers, ac_map)
    core_params = filter_params(params, crypto_set)

    c_frontier = PortfolioConstraints(
        long_only=True,
        max_weight=0.30,
    )
    frontier = compute_frontier(core_params, c_frontier, ac_map, n_points=40)

    fig, ax = plt.subplots(figsize=(10, 6))

    # Frontiera
    if frontier.n_points > 0:
        ax.plot(frontier.volatilities * 100, frontier.returns * 100,
                "b-", linewidth=1.5, alpha=0.5, label="Frontiera efficiente (core)")

    # Profili
    colors = ["#2196F3", "#4CAF50", "#FF9800", "#F44336", "#9C27B0"]
    markers = ["o", "s", "D", "^", "p"]
    for i, r in enumerate(results):
        if r.portfolio.is_feasible():
            s = r.portfolio.stats
            ax.scatter(
                s["volatility"] * 100, s["expected_return"] * 100,
                s=150, c=colors[i], marker=markers[i],
                zorder=5, label=f"{r.profile_name.capitalize()} (target {r.effective_vol_ceiling:.0%})",
                edgecolors="black", linewidth=0.5,
            )

    ax.set_xlabel("Volatilita' annualizzata (%)")
    ax.set_ylabel("Rendimento atteso annualizzato (%)")
    ax.set_title("Profili Investitore: Vol Ceiling come Leva Primaria")
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(True, alpha=0.3)

    chart_path = OUTPUT_DIR / "profili_investitore.png"
    fig.savefig(chart_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"\n  Grafico salvato: {chart_path}")

    print(f"\n{'='*70}\n")


if __name__ == "__main__":
    main()
