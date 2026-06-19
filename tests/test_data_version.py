"""Test per data_version() — invalidazione cache Streamlit."""

import os
import tempfile
import time

import pandas as pd
import pytest

from src.dashboard_data import data_version
from src.cache import DEFAULT_CACHE_DIR


class TestDataVersion:
    def test_returns_float_when_file_exists(self):
        """Se il file di cache esiste, restituisce un float (mtime)."""
        v = data_version()
        # Il file potrebbe non esistere in CI; se esiste dev'essere float
        if v is not None:
            assert isinstance(v, float)

    def test_returns_none_when_missing(self, monkeypatch, tmp_path):
        """Se il file non esiste, restituisce None senza crash."""
        monkeypatch.setattr(
            "src.dashboard_data.DEFAULT_CACHE_DIR", tmp_path / "nonexistent"
        )
        assert data_version() is None

    def test_stable_for_same_file(self):
        """Chiamate successive sullo stesso file danno lo stesso valore."""
        v1 = data_version()
        v2 = data_version()
        assert v1 == v2

    def test_changes_when_file_modified(self, monkeypatch, tmp_path):
        """Quando il file viene modificato, il valore cambia."""
        from src.dashboard_data import DATA_START, DATA_END

        cache_file = tmp_path / f"prices_{DATA_START}_{DATA_END}.parquet"
        # Crea un file parquet finto
        df = pd.DataFrame({"a": [1, 2, 3]})
        df.to_parquet(cache_file, engine="pyarrow")

        monkeypatch.setattr("src.dashboard_data.DEFAULT_CACHE_DIR", tmp_path)

        v1 = data_version()
        assert v1 is not None

        # Modifica il file (cambia mtime)
        time.sleep(0.05)
        os.utime(cache_file, None)

        v2 = data_version()
        assert v2 is not None
        assert v2 != v1
