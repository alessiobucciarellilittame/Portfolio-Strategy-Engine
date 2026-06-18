"""Test per il data provider (richiede connessione internet)."""

import pytest
import pandas as pd
from datetime import date

from src.data_provider import YFinanceProvider


@pytest.mark.network
def test_download_single_ticker():
    """Scarica un singolo ticker noto e verifica il formato."""
    provider = YFinanceProvider()
    df = provider.get_prices(["SWDA.MI"], date(2024, 1, 2), date(2024, 1, 31))

    assert not df.empty
    assert "SWDA.MI" in df.columns
    assert isinstance(df.index, pd.DatetimeIndex)
    assert df["SWDA.MI"].notna().sum() > 10


@pytest.mark.network
def test_download_nonexistent_ticker():
    """Un ticker inesistente deve risultare in colonna NaN, non un crash."""
    provider = YFinanceProvider()
    df = provider.get_prices(["FAKE_TICKER_XYZ123"], date(2024, 1, 2), date(2024, 1, 31))

    # Può restituire DataFrame vuoto o colonna tutta NaN
    if not df.empty and "FAKE_TICKER_XYZ123" in df.columns:
        assert df["FAKE_TICKER_XYZ123"].isna().all()
