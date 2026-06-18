#!/usr/bin/env python3
"""
Script di esempio Fase 7: genera i piani d'investimento PDF.

Produce:
- Un PDF per il profilo Bilanciato (con satellite cripto opzionale)
- Un PDF di confronto dei 5 profili
- Backtest simulato per arricchire i report con equity curve

Uso:
    python scripts/example_report.py
"""

import sys
import logging
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.pipeline import run_pipeline
from src.estimation import estimate_parameters
from src.profiles import build_all_profiles, load_profiles
from src.core_satellite import build_core_satellite
from src.strategies import simulate, PeriodicRebalance
from src.reporting import (
    build_report,
    build_comparison,
    render_pdf,
    render_comparison_pdf,
    validate_report,
)

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

OUTPUT_DIR = Path(__file__).parent.parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# Periodo dati
DATA_START = date(2015, 1, 2)
DATA_END = date(2024, 12, 31)
# Backtest: out-of-sample
SIM_START = date(2020, 1, 2)
HORIZON_YEARS = 5


def main():
    print(f"\n{'='*70}")
    print(f" FASE 7 — REPORTISTICA: Piano d'investimento PDF")
    print(f"{'='*70}")

    # 1. Carica dati e stima parametri
    print(f"\n  Caricamento dati {DATA_START} -> {DATA_END}...")
    bundle = run_pipeline(start=DATA_START, end=DATA_END)
    params = estimate_parameters(
        bundle.returns,
        mean_method="bayes_stein",
        cov_method="ledoit_wolf",
    )
    ac_map = bundle.universe["asset_class"].to_dict()

    # 2. Costruisci tutti i profili
    print(f"  Costruzione profili...")
    all_results = build_all_profiles(
        params, horizon_years=HORIZON_YEARS, asset_class_map=ac_map,
    )

    # 3. Backtest per ogni profilo (simulazione buy&hold su dati fuori campione)
    print(f"  Backtest simulato {SIM_START} -> {DATA_END}...")
    prices_sim = bundle.prices.loc[str(SIM_START):str(DATA_END)]
    strategy = PeriodicRebalance(frequency="quarterly")

    backtest_results = {}
    for pr in all_results:
        if pr.portfolio.is_feasible():
            try:
                bt = simulate(
                    prices_sim,
                    pr.portfolio.weights,
                    strategy,
                    tx_cost_bps=10,
                )
                backtest_results[pr.profile_name] = bt
            except Exception as e:
                print(f"  Backtest '{pr.profile_name}' fallito: {e}")

    # 4. Report singolo: Bilanciato con satellite cripto
    print(f"\n  --- Report singolo: Bilanciato + satellite cripto ---")
    profiles = load_profiles()
    cs = build_core_satellite(
        profiles["bilanciato"], params, ac_map,
        crypto_weight=0.05, horizon_years=HORIZON_YEARS,
    )
    bilanciato_pr = [r for r in all_results if r.profile_name == "bilanciato"][0]
    bilanciato_bt = backtest_results.get("bilanciato")

    report_bilanciato = build_report(
        bilanciato_pr,
        backtest_result=bilanciato_bt,
        core_satellite_result=cs,
        rebalance_frequency="quarterly",
    )

    # Validazione
    issues = validate_report(report_bilanciato)
    if issues:
        print(f"  PROBLEMI: {issues}")
    else:
        print(f"  Validazione report: OK")

    # Stampa riepilogo
    print(f"  Profilo: {report_bilanciato.profile_name}")
    print(f"  Strumenti: {len(report_bilanciato.allocation)}")
    print(f"  Rendimento atteso: {report_bilanciato.expected_return:.2%}")
    print(f"  Volatilita' attesa: {report_bilanciato.expected_volatility:.2%}")
    print(f"  Sharpe atteso: {report_bilanciato.expected_sharpe:.2f}")
    print(f"  Satellite cripto: {report_bilanciato.satellite_weight:.2%}")
    if report_bilanciato.backtest_cagr is not None:
        print(f"  CAGR backtest: {report_bilanciato.backtest_cagr:.2%}")
        print(f"  Max drawdown: {report_bilanciato.backtest_max_drawdown:.2%}")

    # Genera PDF
    try:
        pdf_path = render_pdf(report_bilanciato)
        print(f"\n  PDF generato: {pdf_path}")
    except ImportError as e:
        print(f"\n  PDF non generato: {e}")

    # 5. Report di confronto: tutti i 5 profili
    print(f"\n  --- Report confronto: 5 profili ---")
    reports = []
    for pr in all_results:
        bt = backtest_results.get(pr.profile_name)
        report = build_report(pr, backtest_result=bt, rebalance_frequency="quarterly")
        reports.append(report)

    comparison = build_comparison(reports)

    # Tabella riepilogo
    print(f"\n  {'Profilo':15s}  {'Vol target':>10s}  {'Rend.':>8s}  "
          f"{'Sharpe':>7s}  {'Max DD':>8s}")
    print(f"  {'-'*55}")
    for r in comparison.profiles:
        mdd = f"{r.backtest_max_drawdown:.2%}" if r.backtest_max_drawdown is not None else "n/d"
        print(f"  {r.profile_name:15s}  {r.effective_vol_ceiling:>10.2%}  "
              f"{r.expected_return:>8.2%}  {r.expected_sharpe:>7.2f}  {mdd:>8s}")

    # Genera PDF confronto
    try:
        pdf_path = render_comparison_pdf(comparison)
        print(f"\n  PDF confronto generato: {pdf_path}")
    except ImportError as e:
        print(f"\n  PDF confronto non generato: {e}")

    print(f"\n{'='*70}\n")


if __name__ == "__main__":
    main()
