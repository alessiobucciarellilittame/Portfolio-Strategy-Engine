#!/usr/bin/env python3
"""
Script di esempio Fase 2: stima parametri mu e Sigma.

Uso:
    python scripts/example_estimation.py
"""

import sys
import logging
from datetime import date
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.pipeline import run_pipeline
from src.estimation import estimate_parameters

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


def main():
    # 1. Carica dati dalla Fase 1 (usa la cache se disponibile)
    print(f"\n{'='*70}")
    print(f" FASE 2 - Stima dei Parametri")
    print(f"{'='*70}\n")

    bundle = run_pipeline(start=date(2023, 1, 2), end=date(2024, 12, 31))
    returns = bundle.returns

    # 2. Combinazioni di stimatori da confrontare
    configs = [
        ("historical",  "sample"),
        ("james_stein", "ledoit_wolf"),
        ("bayes_stein", "oas"),
    ]

    results = {}
    for mean_m, cov_m in configs:
        label = f"{mean_m} + {cov_m}"
        print(f"\n--- {label} ---")
        est = estimate_parameters(returns, mean_method=mean_m, cov_method=cov_m)
        results[label] = est

    # 3. Confronto rendimenti attesi annualizzati
    print(f"\n{'='*70}")
    print(f" RENDIMENTI ATTESI ANNUALIZZATI (mu)")
    print(f"{'='*70}")
    tickers = results[list(results.keys())[0]].tickers
    header = f"{'Ticker':20s}"
    for label in results:
        header += f"  {label:>28s}"
    print(header)
    print("-" * len(header))

    for i, ticker in enumerate(tickers):
        row = f"{ticker:20s}"
        for label, est in results.items():
            row += f"  {est.mu[i]:>27.2%}"
        print(row)

    # 4. Confronto volatilità annualizzate
    print(f"\n{'='*70}")
    print(f" VOLATILITA' ANNUALIZZATE")
    print(f"{'='*70}")
    print(header)
    print("-" * len(header))

    for i, ticker in enumerate(tickers):
        row = f"{ticker:20s}"
        for label, est in results.items():
            vol = est.volatilities()[i]
            row += f"  {vol:>27.2%}"
        print(row)

    # 5. Confronto condition number e shrinkage
    print(f"\n{'='*70}")
    print(f" CONDIZIONAMENTO E SHRINKAGE")
    print(f"{'='*70}")
    print(f"{'Configurazione':35s}  {'Cond. Number':>14s}  {'Shrink mu':>10s}  {'Shrink cov':>10s}")
    print("-" * 75)
    for label, est in results.items():
        cond = est.metadata["condition_number"]
        s_mu = est.metadata["mean_shrinkage"]
        s_cov = est.metadata["cov_shrinkage"]
        print(f"{label:35s}  {cond:>14.1f}  {s_mu:>10.4f}  {s_cov:>10.4f}")

    # 6. Problemi di validazione
    print(f"\n{'='*70}")
    print(f" VALIDAZIONE")
    print(f"{'='*70}")
    for label, est in results.items():
        issues = est.metadata.get("validation_issues", [])
        if issues:
            print(f"\n  {label}:")
            for issue in issues:
                print(f"    - {issue}")
        else:
            print(f"  {label}: OK (nessun problema)")

    # 7. Dettagli
    ref = results[list(results.keys())[0]]
    print(f"\n  Periodo:              {ref.metadata['date_start']} -> {ref.metadata['date_end']}")
    print(f"  Osservazioni:         {ref.metadata['n_observations']}")
    print(f"  Fattore annualizzaz.: {ref.metadata['ann_factor']}")
    print(f"  Numero asset:         {ref.n_assets}")

    print(f"\n{'='*70}\n")


if __name__ == "__main__":
    main()
