"""Test per il modulo di pulizia dati."""

import pandas as pd
import numpy as np
import pytest
from datetime import date

from src.cleaning import (
    build_reference_calendar,
    align_to_calendar,
    controlled_ffill,
    detect_outliers,
)


def test_reference_calendar_excludes_weekends():
    """Il calendario di riferimento deve avere solo business days."""
    cal = build_reference_calendar(date(2024, 1, 1), date(2024, 1, 14))
    # 1-14 gen 2024: lun 1, mar 2, ..., ven 5, lun 8, ..., ven 12
    # 13 e 14 sono sab e dom
    for dt in cal:
        assert dt.dayofweek < 5, f"{dt} è un weekend"


def test_align_to_calendar():
    """Allineamento: i giorni assenti nel DataFrame diventano NaN."""
    cal = pd.bdate_range("2024-01-01", "2024-01-05", name="date")
    # Prezzi solo per 2 giorni su 5
    prices = pd.DataFrame(
        {"A": [100.0, 102.0]},
        index=pd.DatetimeIndex([cal[0], cal[2]], name="date"),
    )
    aligned = align_to_calendar(prices, cal)
    assert len(aligned) == len(cal)
    assert aligned["A"].isna().sum() == 3  # 3 giorni mancanti


def test_controlled_ffill_respects_limit():
    """Forward-fill deve fermarsi dopo max_days."""
    idx = pd.bdate_range("2024-01-01", periods=10, name="date")
    data = pd.DataFrame({"A": [100.0] + [np.nan] * 9}, index=idx)

    filled, mask = controlled_ffill(data, max_days=3)
    # I primi 3 NaN vengono riempiti, i successivi restano NaN
    assert filled["A"].iloc[1] == 100.0  # fill 1
    assert filled["A"].iloc[3] == 100.0  # fill 3
    assert pd.isna(filled["A"].iloc[4])  # troppo lontano


def test_detect_outliers_finds_extreme_return():
    """Un rendimento del +50% per un'azione deve essere segnalato."""
    idx = pd.bdate_range("2024-01-01", periods=3, name="date")
    prices = pd.DataFrame({"A": [100.0, 100.0, 160.0]}, index=idx)

    outliers = detect_outliers(prices, {"A": "equity"})
    assert len(outliers) == 1
    assert outliers.iloc[0]["ticker"] == "A"


def test_detect_outliers_crypto_high_threshold():
    """Un +30% per crypto non è outlier (soglia 50%)."""
    idx = pd.bdate_range("2024-01-01", periods=3, name="date")
    prices = pd.DataFrame({"BTC": [100.0, 100.0, 130.0]}, index=idx)

    outliers = detect_outliers(prices, {"BTC": "crypto"})
    assert len(outliers) == 0
