"""
Pipeline principale del modulo dati.

Orchestra: download -> conversione FX -> pulizia -> validazione -> cache.

OUTPUT (contratto per le fasi successive):
    DataBundle con:
    - prices: pd.DataFrame di prezzi puliti in EUR
              index = DatetimeIndex (business days), colonne = ticker
    - returns: pd.DataFrame di rendimenti giornalieri semplici
              index = DatetimeIndex, colonne = ticker
    - universe: pd.DataFrame con metadati strumenti
    - validation_report: risultato della validazione
"""

import logging
from dataclasses import dataclass
from datetime import date

import pandas as pd

from .universe import load_universe, get_tickers, get_fx_pairs_needed
from .data_provider import DataProvider, YFinanceProvider
from .fx import download_fx_rates, convert_to_base_currency
from .cleaning import clean_prices
from .validation import validate_prices, ValidationReport
from .cache import DataCache

logger = logging.getLogger(__name__)

BASE_CURRENCY = "EUR"


@dataclass
class DataBundle:
    """Contratto di output del modulo dati.

    Questo è l'oggetto che le fasi successive riceveranno.
    """
    prices: pd.DataFrame       # Prezzi puliti in EUR, index=date, columns=ticker
    returns: pd.DataFrame      # Rendimenti giornalieri semplici
    universe: pd.DataFrame     # Metadati strumenti
    validation_report: ValidationReport
    outliers: pd.DataFrame     # Outlier rilevati
    fill_mask: pd.DataFrame    # Dove è stato applicato forward-fill


def run_pipeline(
    start: date,
    end: date,
    provider: DataProvider | None = None,
    universe_path=None,
    use_cache: bool = True,
    refresh_cache: bool = False,
) -> DataBundle:
    """Esegue la pipeline completa del modulo dati.

    Parametri:
        start: data inizio
        end: data fine (ATTENZIONE: non deve essere nel futuro rispetto a oggi)
        provider: fonte dati (default: YFinanceProvider)
        universe_path: percorso file universo (default: config/universe.yaml)
        use_cache: se True, usa la cache locale
        refresh_cache: se True, forza il re-download anche se la cache esiste
    """
    provider = provider or YFinanceProvider()
    cache = DataCache()
    cache_key = f"prices_{start}_{end}"

    # 1. Carica universo
    universe = load_universe(universe_path)
    tickers = get_tickers(universe)
    logger.info(f"Universo: {len(tickers)} strumenti")

    # Mappa ticker -> valuta e ticker -> asset_class
    currency_map = universe["currency"].to_dict()
    asset_class_map = universe["asset_class"].to_dict()

    # 2. Download prezzi (o carica da cache)
    if use_cache and not refresh_cache and cache.exists(cache_key):
        logger.info("Caricamento prezzi da cache")
        prices_eur = cache.load(cache_key)
    else:
        # 2a. Scarica prezzi grezzi
        logger.info("Download prezzi grezzi...")
        raw_prices = provider.get_prices(tickers, start, end)

        # 2b. Scarica e applica conversione FX
        foreign_ccys = [
            ccy for ccy in universe["currency"].unique() if ccy != BASE_CURRENCY
        ]
        if foreign_ccys:
            logger.info(f"Download tassi FX per: {foreign_ccys}")
            fx_rates = download_fx_rates(provider, foreign_ccys, BASE_CURRENCY, start, end)
            prices_eur = convert_to_base_currency(raw_prices, currency_map, fx_rates, BASE_CURRENCY)
        else:
            prices_eur = raw_prices

        # 2c. Salva in cache
        if use_cache:
            cache.save(cache_key, prices_eur)

    # 3. Pulizia e allineamento
    logger.info("Pulizia e allineamento...")
    prices_clean, fill_mask, outliers = clean_prices(
        prices_eur, start, end, asset_class_map
    )

    # 4. Calcola rendimenti (nessun lookahead: rendimento al tempo t usa prezzo t e t-1)
    returns = prices_clean.pct_change()
    # La prima riga è NaN per definizione (non c'è t-1): la teniamo per trasparenza

    # 5. Validazione
    logger.info("Validazione dati...")
    report = validate_prices(prices_clean, asset_class_map)
    logger.info(report.summary())

    return DataBundle(
        prices=prices_clean,
        returns=returns,
        universe=universe,
        validation_report=report,
        outliers=outliers,
        fill_mask=fill_mask,
    )
