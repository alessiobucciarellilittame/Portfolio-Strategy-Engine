"""
Pulizia e allineamento delle serie prezzi.

- Allineamento su calendario comune (business days europei)
- Forward-fill controllato per dati mancanti
- Rilevamento outlier
"""

import logging
from datetime import date

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

# Soglia massima per rendimento giornaliero assoluto (per asset class)
RETURN_THRESHOLDS = {
    "equity": 0.20,     # 20%
    "bond": 0.10,       # 10%
    "commodity": 0.15,  # 15%
    "crypto": 0.50,     # 50% (le crypto sono molto volatili)
}
DEFAULT_THRESHOLD = 0.25

# Massimo numero di giorni consecutivi di forward-fill
MAX_FFILL_DAYS = 5


def build_reference_calendar(start: date, end: date) -> pd.DatetimeIndex:
    """Crea un calendario di riferimento basato sui business days europei.

    Usiamo i business days standard (lun-ven) come base comune.
    Le cripto quotano 24/7 ma le allineiamo a questo calendario.
    """
    start_ts = pd.Timestamp(start) if not isinstance(start, pd.Timestamp) else start
    end_ts = pd.Timestamp(end) if not isinstance(end, pd.Timestamp) else end
    return pd.bdate_range(start=start_ts, end=end_ts, name="date")


def align_to_calendar(
    prices: pd.DataFrame,
    calendar: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Riallinea i prezzi sul calendario di riferimento.

    I giorni mancanti vengono riempiti con NaN (il fill avviene dopo).
    """
    return prices.reindex(calendar)


def controlled_ffill(
    prices: pd.DataFrame,
    max_days: int = MAX_FFILL_DAYS,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Forward-fill controllato: riempie al massimo max_days consecutivi.

    Restituisce:
        - DataFrame con prezzi riempiti
        - DataFrame booleano che indica dove è stato applicato il fill
    """
    filled = prices.ffill(limit=max_days)
    was_filled = prices.isna() & filled.notna()

    # Log riassuntivo
    fill_counts = was_filled.sum()
    for ticker in fill_counts[fill_counts > 0].index:
        logger.info(f"{ticker}: {fill_counts[ticker]} giorni riempiti con forward-fill")

    # Segnala dove il gap era troppo lungo (rimasto NaN dopo ffill limitato)
    still_missing = filled.isna() & ~prices.columns.isin([])  # tutte le colonne
    still_nan = filled.isna().sum()
    for ticker in still_nan[still_nan > 0].index:
        logger.warning(
            f"{ticker}: {still_nan[ticker]} valori ancora mancanti dopo ffill "
            f"(gap > {max_days} giorni)"
        )

    return filled, was_filled


def detect_outliers(
    prices: pd.DataFrame,
    asset_class_map: dict[str, str],
) -> pd.DataFrame:
    """Rileva rendimenti giornalieri anomali (possibili errori di feed).

    Restituisce un DataFrame con le righe sospette:
    ticker, date, return, threshold
    """
    returns = prices.pct_change()
    outliers = []

    for ticker in returns.columns:
        ac = asset_class_map.get(ticker, "equity")
        threshold = RETURN_THRESHOLDS.get(ac, DEFAULT_THRESHOLD)

        abs_ret = returns[ticker].abs()
        suspect = abs_ret[abs_ret > threshold].dropna()

        for dt, ret_val in suspect.items():
            outliers.append({
                "ticker": ticker,
                "date": dt,
                "return": ret_val,
                "threshold": threshold,
                "asset_class": ac,
            })
            logger.warning(
                f"OUTLIER: {ticker} il {dt.date()}: rendimento {ret_val:+.2%} "
                f"(soglia {ac}: +/-{threshold:.0%})"
            )

    if not outliers:
        logger.info("Nessun outlier rilevato")

    return pd.DataFrame(outliers)


def clean_prices(
    raw_prices: pd.DataFrame,
    start,
    end,
    asset_class_map: dict[str, str],
    max_ffill_days: int = MAX_FFILL_DAYS,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Pipeline completa di pulizia.

    Restituisce:
        - prices_clean: prezzi puliti e allineati
        - fill_mask: dove è stato applicato forward-fill
        - outliers: DataFrame degli outlier rilevati
    """
    calendar = build_reference_calendar(start, end)
    aligned = align_to_calendar(raw_prices, calendar)
    filled, fill_mask = controlled_ffill(aligned, max_ffill_days)
    outliers = detect_outliers(filled, asset_class_map)

    return filled, fill_mask, outliers
