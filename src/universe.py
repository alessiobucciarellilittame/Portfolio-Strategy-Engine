"""
Gestione dell'universo di strumenti finanziari.
Carica la configurazione da YAML e fornisce accesso ai metadati.
"""

import yaml
import pandas as pd
from pathlib import Path
from typing import Optional

# Percorso di default del file universo
DEFAULT_UNIVERSE_PATH = Path(__file__).parent.parent / "config" / "universe.yaml"


def load_universe(path: Optional[Path] = None) -> pd.DataFrame:
    """Carica l'universo strumenti dal file YAML e restituisce un DataFrame.

    Colonne: ticker, name, asset_class, region, currency, ter
    """
    path = path or DEFAULT_UNIVERSE_PATH
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    instruments = data["instruments"]
    df = pd.DataFrame(instruments)
    df = df.set_index("ticker")
    return df


def get_tickers(universe: pd.DataFrame, asset_class: Optional[str] = None) -> list[str]:
    """Restituisce la lista dei ticker, opzionalmente filtrata per asset class."""
    if asset_class:
        return universe[universe["asset_class"] == asset_class].index.tolist()
    return universe.index.tolist()


def get_fx_pairs_needed(universe: pd.DataFrame, base_currency: str = "EUR") -> list[str]:
    """Determina quali coppie FX servono per convertire in valuta base.

    Restituisce lista di ticker Yahoo Finance per i tassi di cambio necessari.
    Es. per USD -> EUR restituisce 'USDEUR=X'
    """
    foreign_currencies = (
        universe["currency"]
        .unique()
    )
    pairs = []
    for ccy in foreign_currencies:
        if ccy != base_currency:
            # Formato Yahoo Finance: USDEUR=X
            pairs.append(f"{ccy}{base_currency}=X")
    return pairs
