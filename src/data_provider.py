"""
Astrazione della fonte dati e implementazione concreta con yfinance.

L'interfaccia DataProvider permette di sostituire la fonte dati
senza modificare il resto del codice.
"""

from abc import ABC, abstractmethod
from datetime import date
import logging

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


class DataProvider(ABC):
    """Interfaccia astratta per qualsiasi fonte dati prezzi."""

    @abstractmethod
    def get_prices(
        self, tickers: list[str], start: date, end: date
    ) -> pd.DataFrame:
        """Scarica i prezzi adjusted close per i ticker indicati.

        Parametri:
            tickers: lista di ticker
            start: data inizio (inclusa)
            end: data fine (inclusa)

        Restituisce:
            DataFrame con DatetimeIndex e una colonna per ticker.
            I valori mancanti sono NaN (non riempiti).
        """
        ...


class YFinanceProvider(DataProvider):
    """Provider concreto basato su yfinance."""

    def get_prices(
        self, tickers: list[str], start: date, end: date
    ) -> pd.DataFrame:
        """Scarica adjusted close da Yahoo Finance.

        Usa 'Close' che in yfinance >= 0.2.31 corrisponde all'adjusted close
        (corretto per dividendi e split).
        """
        if not tickers:
            return pd.DataFrame()

        logger.info(f"Download prezzi per {len(tickers)} ticker: {start} -> {end}")

        # yfinance: end è esclusivo, aggiungiamo 1 giorno
        end_exclusive = pd.Timestamp(end) + pd.Timedelta(days=1)

        data = yf.download(
            tickers=tickers,
            start=str(start),
            end=str(end_exclusive.date()),
            auto_adjust=True,   # Close = adjusted close
            progress=False,
            threads=True,
        )

        if data.empty:
            logger.warning("Nessun dato scaricato da yfinance")
            return pd.DataFrame()

        # yf.download con più ticker restituisce MultiIndex (campo, ticker)
        # Con un solo ticker restituisce colonne semplici
        if isinstance(data.columns, pd.MultiIndex):
            prices = data["Close"]
        else:
            # Un solo ticker: il DataFrame ha colonne [Open, High, Low, Close, Volume]
            prices = data[["Close"]].rename(columns={"Close": tickers[0]})

        # Assicura che le colonne siano i ticker richiesti
        prices = prices.reindex(columns=tickers)
        prices.index = pd.to_datetime(prices.index)
        prices.index.name = "date"

        missing = [t for t in tickers if t not in prices.columns or prices[t].isna().all()]
        if missing:
            logger.warning(f"Ticker senza dati: {missing}")

        return prices
