"""
Conversione valutaria delle serie prezzi in EUR.

Scarica i tassi di cambio necessari e converte le serie
quotate in valuta estera nella valuta base (EUR).
"""

import logging
from datetime import date

import pandas as pd

from .data_provider import DataProvider

logger = logging.getLogger(__name__)


def download_fx_rates(
    provider: DataProvider,
    currencies: list[str],
    base: str,
    start: date,
    end: date,
) -> pd.DataFrame:
    """Scarica i tassi di cambio verso la valuta base.

    Parametri:
        currencies: lista di valute estere (es. ["USD", "GBP"])
        base: valuta target (es. "EUR")

    Restituisce:
        DataFrame con colonne = valute estere, valori = tasso ccy/base
        (es. colonna "USD" contiene il tasso USDEUR)
    """
    if not currencies:
        return pd.DataFrame()

    fx_tickers = [f"{ccy}{base}=X" for ccy in currencies]
    fx_raw = provider.get_prices(fx_tickers, start, end)

    # Rinomina colonne da "USDEUR=X" a "USD"
    rename_map = {f"{ccy}{base}=X": ccy for ccy in currencies}
    fx_rates = fx_raw.rename(columns=rename_map)

    # Forward-fill per giorni festivi (i mercati FX possono avere buchi)
    fx_rates = fx_rates.ffill()

    return fx_rates


def convert_to_base_currency(
    prices: pd.DataFrame,
    currency_map: dict[str, str],
    fx_rates: pd.DataFrame,
    base: str = "EUR",
) -> pd.DataFrame:
    """Converte le serie prezzi nella valuta base.

    Parametri:
        prices: DataFrame con prezzi in valuta originale
        currency_map: dict ticker -> valuta di quotazione (es. {"SPY": "USD"})
        fx_rates: tassi di cambio (output di download_fx_rates)
        base: valuta target

    Restituisce:
        DataFrame con tutti i prezzi espressi in valuta base.
    """
    converted = prices.copy()

    for ticker in prices.columns:
        ccy = currency_map.get(ticker, base)
        if ccy == base:
            continue  # Già in valuta base

        if ccy not in fx_rates.columns:
            logger.error(f"Tasso FX mancante per {ccy}, ticker {ticker} non convertito")
            continue

        # Allinea le date tra prezzo e tasso FX
        rate = fx_rates[ccy].reindex(prices.index).ffill()
        converted[ticker] = prices[ticker] * rate

        logger.info(f"{ticker}: convertito da {ccy} a {base}")

    return converted
