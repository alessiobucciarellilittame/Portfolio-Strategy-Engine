"""Configurazione pytest per il progetto."""

import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--network", action="store_true", default=False,
        help="Esegui anche i test che richiedono connessione internet"
    )


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--network"):
        skip_network = pytest.mark.skip(reason="Richiede --network per eseguire")
        for item in items:
            if "network" in item.keywords:
                item.add_marker(skip_network)
