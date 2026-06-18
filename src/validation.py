"""
Validazione automatica dei dati.

Controlli:
- Nessun prezzo nullo, zero o negativo
- Date ordinate e senza buchi anomali
- Rendimenti giornalieri entro soglie sensate
- Copertura storica minima per ogni strumento
"""

import logging
from dataclasses import dataclass, field

import pandas as pd
import numpy as np

from .cleaning import RETURN_THRESHOLDS, DEFAULT_THRESHOLD

logger = logging.getLogger(__name__)


@dataclass
class ValidationReport:
    """Risultato della validazione."""
    passed: bool = True
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    def add_issue(self, msg: str):
        self.passed = False
        self.issues.append(msg)
        logger.error(f"VALIDAZIONE FALLITA: {msg}")

    def add_warning(self, msg: str):
        self.warnings.append(msg)
        logger.warning(f"VALIDAZIONE AVVISO: {msg}")

    def summary(self) -> str:
        lines = []
        status = "PASSATA" if self.passed else "FALLITA"
        lines.append(f"Validazione: {status}")
        lines.append(f"  Errori: {len(self.issues)}, Avvisi: {len(self.warnings)}")
        for issue in self.issues:
            lines.append(f"  [ERRORE] {issue}")
        for warn in self.warnings:
            lines.append(f"  [AVVISO] {warn}")
        if self.stats:
            lines.append("  Statistiche:")
            for k, v in self.stats.items():
                lines.append(f"    {k}: {v}")
        return "\n".join(lines)


def validate_prices(
    prices: pd.DataFrame,
    asset_class_map: dict[str, str],
    min_coverage_pct: float = 0.80,
    min_history_days: int = 252,
) -> ValidationReport:
    """Esegue tutti i controlli di validazione sui prezzi puliti.

    Parametri:
        prices: prezzi puliti (dopo cleaning)
        asset_class_map: ticker -> asset_class
        min_coverage_pct: % minima di dati non-NaN richiesta
        min_history_days: giorni minimi di storia richiesti
    """
    report = ValidationReport()

    if prices.empty:
        report.add_issue("DataFrame prezzi vuoto")
        return report

    n_dates = len(prices)
    report.stats["n_dates"] = n_dates
    report.stats["date_range"] = f"{prices.index.min().date()} -> {prices.index.max().date()}"
    report.stats["n_tickers"] = len(prices.columns)

    # 1. Date ordinate
    if not prices.index.is_monotonic_increasing:
        report.add_issue("Le date non sono ordinate in modo crescente")

    # 2. Buchi anomali nelle date (gap > 5 business days)
    date_diffs = prices.index.to_series().diff().dt.days.dropna()
    big_gaps = date_diffs[date_diffs > 7]  # > 7 giorni calendario = sospetto
    if len(big_gaps) > 0:
        for dt, gap in big_gaps.items():
            report.add_warning(f"Gap di {int(gap)} giorni prima del {dt.date()}")

    for ticker in prices.columns:
        series = prices[ticker]

        # 3. Copertura storica
        valid_count = series.notna().sum()
        coverage = valid_count / n_dates if n_dates > 0 else 0
        report.stats[f"{ticker}_coverage"] = f"{coverage:.1%}"

        if valid_count < min_history_days:
            report.add_warning(
                f"{ticker}: solo {valid_count} giorni di dati "
                f"(minimo richiesto: {min_history_days})"
            )

        if coverage < min_coverage_pct:
            report.add_warning(
                f"{ticker}: copertura {coverage:.1%} sotto soglia {min_coverage_pct:.0%}"
            )

        valid = series.dropna()
        if valid.empty:
            report.add_issue(f"{ticker}: nessun dato valido")
            continue

        # 4. Prezzi nulli, zero o negativi
        n_zero = (valid == 0).sum()
        n_neg = (valid < 0).sum()
        if n_zero > 0:
            report.add_issue(f"{ticker}: {n_zero} prezzi pari a zero")
        if n_neg > 0:
            report.add_issue(f"{ticker}: {n_neg} prezzi negativi")

        # 5. Rendimenti entro soglie
        returns = valid.pct_change().dropna()
        ac = asset_class_map.get(ticker, "equity")
        threshold = RETURN_THRESHOLDS.get(ac, DEFAULT_THRESHOLD)

        extreme = returns[returns.abs() > threshold]
        if len(extreme) > 0:
            report.add_warning(
                f"{ticker}: {len(extreme)} rendimenti oltre soglia "
                f"{threshold:.0%} ({ac})"
            )

        # 6. NaN residui
        n_nan = series.isna().sum()
        if n_nan > 0:
            report.add_warning(f"{ticker}: {n_nan} valori NaN residui")

    return report
