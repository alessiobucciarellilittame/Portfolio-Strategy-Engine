"""
Caching locale dei dati su disco in formato Parquet.

Salva i dati scaricati per evitare download ripetuti e
garantire riproducibilità. Supporta aggiornamento incrementale.
"""

import logging
from pathlib import Path
from datetime import date

import pandas as pd

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = Path(__file__).parent.parent / "cache"


class DataCache:
    """Gestisce il caching locale dei dati in formato Parquet."""

    def __init__(self, cache_dir: Path = DEFAULT_CACHE_DIR):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, name: str) -> Path:
        """Percorso del file cache per un dato nome."""
        return self.cache_dir / f"{name}.parquet"

    def exists(self, name: str) -> bool:
        return self._path(name).exists()

    def save(self, name: str, df: pd.DataFrame) -> None:
        """Salva un DataFrame in cache."""
        path = self._path(name)
        df.to_parquet(path, engine="pyarrow")
        logger.info(f"Cache salvata: {path} ({len(df)} righe)")

    def load(self, name: str) -> pd.DataFrame:
        """Carica un DataFrame dalla cache."""
        path = self._path(name)
        if not path.exists():
            raise FileNotFoundError(f"Cache non trovata: {path}")
        df = pd.read_parquet(path, engine="pyarrow")
        logger.info(f"Cache caricata: {path} ({len(df)} righe)")
        return df

    def get_date_range(self, name: str) -> tuple[date, date] | None:
        """Restituisce l'intervallo di date nella cache, o None se non esiste."""
        if not self.exists(name):
            return None
        df = self.load(name)
        if df.empty:
            return None
        return df.index.min().date(), df.index.max().date()

    def clear(self, name: str) -> None:
        """Elimina un file dalla cache."""
        path = self._path(name)
        if path.exists():
            path.unlink()
            logger.info(f"Cache eliminata: {path}")

    def clear_all(self) -> None:
        """Elimina tutti i file dalla cache."""
        for f in self.cache_dir.glob("*.parquet"):
            f.unlink()
            logger.info(f"Cache eliminata: {f}")
