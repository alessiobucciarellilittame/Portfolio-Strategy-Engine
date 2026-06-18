"""
Sanity check: confronto con valori reali noti.

Verifica che i dati scaricati siano ragionevoli confrontandoli
con riferimenti pubblicamente noti.
"""

import pytest
import pandas as pd
from datetime import date

from src.data_provider import YFinanceProvider


@pytest.mark.network
def test_btc_eur_known_value():
    """Verifica che il prezzo di BTC-EUR a fine 2024 sia nell'ordine di grandezza giusto.

    A fine dicembre 2024, BTC era intorno ai 90.000-100.000 EUR.
    Questo test verifica ordine di grandezza, non il prezzo esatto.
    """
    provider = YFinanceProvider()
    df = provider.get_prices(["BTC-EUR"], date(2024, 12, 1), date(2024, 12, 31))

    assert not df.empty, "Nessun dato per BTC-EUR"
    last_price = df["BTC-EUR"].dropna().iloc[-1]

    # BTC a dic 2024: tra 50k e 150k EUR (range largo per robustezza)
    assert 50_000 < last_price < 150_000, (
        f"Prezzo BTC-EUR ({last_price:.0f}) fuori range atteso 50k-150k"
    )


@pytest.mark.network
def test_swda_positive_return_2024():
    """Verifica che MSCI World (SWDA) abbia avuto rendimento positivo nel 2024.

    Il 2024 è stato un anno positivo per l'azionario globale (circa +20%).
    """
    provider = YFinanceProvider()
    df = provider.get_prices(["SWDA.MI"], date(2024, 1, 2), date(2024, 12, 31))

    assert not df.empty, "Nessun dato per SWDA.MI"
    prices = df["SWDA.MI"].dropna()
    cumulative_return = (prices.iloc[-1] / prices.iloc[0]) - 1

    # Rendimento 2024 MSCI World: positivo, tra +5% e +40%
    assert 0.05 < cumulative_return < 0.40, (
        f"Rendimento SWDA 2024: {cumulative_return:.1%}, fuori range atteso 5%-40%"
    )
