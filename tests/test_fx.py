"""Test per il modulo di conversione valutaria."""

import pandas as pd
import numpy as np
import pytest
from datetime import date

from src.fx import convert_to_base_currency


def test_convert_eur_unchanged():
    """Strumenti già in EUR non devono essere modificati."""
    idx = pd.bdate_range("2024-01-01", periods=3, name="date")
    prices = pd.DataFrame({"SWDA.MI": [10.0, 10.5, 11.0]}, index=idx)
    fx = pd.DataFrame({"USD": [0.92, 0.93, 0.91]}, index=idx)

    result = convert_to_base_currency(prices, {"SWDA.MI": "EUR"}, fx)
    pd.testing.assert_frame_equal(result, prices)


def test_convert_usd_to_eur():
    """Conversione USD -> EUR moltiplica per il tasso."""
    idx = pd.bdate_range("2024-01-01", periods=3, name="date")
    prices = pd.DataFrame({"SPY": [100.0, 101.0, 102.0]}, index=idx)
    fx = pd.DataFrame({"USD": [0.90, 0.90, 0.90]}, index=idx)

    result = convert_to_base_currency(prices, {"SPY": "USD"}, fx)
    expected = pd.DataFrame({"SPY": [90.0, 90.9, 91.8]}, index=idx)
    pd.testing.assert_frame_equal(result, expected)


def test_missing_fx_rate_not_converted():
    """Se manca il tasso FX, il ticker non viene convertito (resta in valuta originale)."""
    idx = pd.bdate_range("2024-01-01", periods=3, name="date")
    prices = pd.DataFrame({"X": [100.0, 101.0, 102.0]}, index=idx)
    fx = pd.DataFrame(index=idx)  # Nessun tasso FX

    result = convert_to_base_currency(prices, {"X": "GBP"}, fx)
    # Senza conversione, i valori restano uguali
    pd.testing.assert_frame_equal(result, prices)
