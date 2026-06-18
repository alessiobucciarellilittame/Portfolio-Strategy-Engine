#!/usr/bin/env python3
"""
Script di esempio: scarica, pulisce e valida i dati dell'universo.

Uso:
    python scripts/example.py
    python scripts/example.py --refresh   # forza re-download
"""

import sys
import logging
import argparse
from datetime import date
from pathlib import Path

# Aggiungi root del progetto al path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.pipeline import run_pipeline

# Configurazione logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


def main():
    parser = argparse.ArgumentParser(description="Pipeline dati - esempio")
    parser.add_argument("--refresh", action="store_true", help="Forza re-download")
    parser.add_argument("--start", default="2023-01-02", help="Data inizio (YYYY-MM-DD)")
    parser.add_argument("--end", default="2024-12-31", help="Data fine (YYYY-MM-DD)")
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)

    print(f"\n{'='*60}")
    print(f" Portfolio Strategy Engine - Modulo Dati")
    print(f" Intervallo: {start} -> {end}")
    print(f"{'='*60}\n")

    bundle = run_pipeline(start=start, end=end, refresh_cache=args.refresh)

    # --- Riepilogo ---
    print(f"\n{'='*60}")
    print(f" RIEPILOGO")
    print(f"{'='*60}")
    print(f" Strumenti nell'universo: {len(bundle.universe)}")
    print(f" Strumenti con dati:      {bundle.prices.notna().any().sum()}")
    print(f" Date coperte:            {len(bundle.prices)}")
    print(f" Intervallo date:         {bundle.prices.index.min().date()} -> "
          f"{bundle.prices.index.max().date()}")
    print()

    # Copertura per strumento
    print(" Copertura per strumento:")
    for ticker in bundle.prices.columns:
        n_valid = bundle.prices[ticker].notna().sum()
        pct = n_valid / len(bundle.prices) * 100
        last_price = bundle.prices[ticker].dropna().iloc[-1] if n_valid > 0 else float("nan")
        print(f"   {ticker:20s}  {n_valid:5d}/{len(bundle.prices)} ({pct:5.1f}%)  "
              f"ultimo prezzo EUR: {last_price:>12.2f}")
    print()

    # Outlier
    if len(bundle.outliers) > 0:
        print(f" Outlier rilevati: {len(bundle.outliers)}")
        for _, row in bundle.outliers.iterrows():
            print(f"   {row['ticker']} {row['date'].date()}: {row['return']:+.2%}")
    else:
        print(" Nessun outlier rilevato")
    print()

    # Validazione
    print(f" {bundle.validation_report.summary()}")
    print()

    # Primi rendimenti
    print(" Ultime 5 righe dei rendimenti giornalieri:")
    print(bundle.returns.tail().to_string())
    print(f"\n{'='*60}\n")


if __name__ == "__main__":
    main()
