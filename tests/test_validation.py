"""Test per il modulo di validazione."""

import pandas as pd
import numpy as np
import pytest

from src.validation import validate_prices


def _make_prices(values, start="2024-01-01", ticker="A"):
    idx = pd.bdate_range(start, periods=len(values), name="date")
    return pd.DataFrame({ticker: values}, index=idx)


def test_valid_data_passes():
    """Dati puliti normali devono passare la validazione."""
    prices = _make_prices([100 + i * 0.5 for i in range(300)])
    report = validate_prices(prices, {"A": "equity"}, min_history_days=100)
    assert report.passed


def test_zero_prices_fail():
    """Prezzi a zero devono generare un errore."""
    prices = _make_prices([100.0, 0.0, 101.0])
    report = validate_prices(prices, {"A": "equity"}, min_history_days=1)
    assert not report.passed
    assert any("zero" in i for i in report.issues)


def test_negative_prices_fail():
    """Prezzi negativi devono generare un errore."""
    prices = _make_prices([100.0, -5.0, 101.0])
    report = validate_prices(prices, {"A": "equity"}, min_history_days=1)
    assert not report.passed
    assert any("negativ" in i for i in report.issues)


def test_empty_dataframe_fails():
    """DataFrame vuoto deve fallire la validazione."""
    prices = pd.DataFrame()
    report = validate_prices(prices, {})
    assert not report.passed


def test_low_coverage_warns():
    """Copertura insufficiente deve generare un avviso."""
    values = [100.0] * 50 + [np.nan] * 200
    prices = _make_prices(values)
    report = validate_prices(prices, {"A": "equity"}, min_coverage_pct=0.80)
    assert any("copertura" in w for w in report.warnings)
