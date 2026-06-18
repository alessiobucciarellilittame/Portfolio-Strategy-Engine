"""
Configurazione centralizzata del tasso risk-free.

Unico punto di verita' per il tasso risk-free usato in tutti i calcoli
di Sharpe ratio nel progetto (Fasi 3, 5, 6 e core-satellite).

Due modalita':
(a) Valore costante configurabile (default: 2%)
(b) Serie storica di tassi (es. tasso a breve EUR), per Sharpe
    coerenti col periodo nei backtest

Uso:
    from src.config import get_risk_free_rate, set_risk_free_rate

    # Costante
    set_risk_free_rate(0.025)

    # Serie storica
    set_risk_free_series(pd.Series([0.01, 0.02, 0.03], index=dates))

    # Lettura
    rf = get_risk_free_rate()               # costante
    rf = get_risk_free_rate(as_of=some_date) # da serie se disponibile
"""

import pandas as pd

# Default: 2% annualizzato (BCE deposit facility rate approssimato)
_risk_free_rate: float = 0.02
_risk_free_series: pd.Series | None = None


def get_risk_free_rate(as_of=None) -> float:
    """Restituisce il tasso risk-free annualizzato.

    Se e' impostata una serie storica e as_of e' fornito,
    restituisce il tasso piu' recente disponibile <= as_of.
    Altrimenti restituisce il valore costante configurato.
    """
    if _risk_free_series is not None and as_of is not None:
        ts = pd.Timestamp(as_of)
        valid = _risk_free_series.loc[:ts]
        if len(valid) > 0:
            return float(valid.iloc[-1])
    return _risk_free_rate


def set_risk_free_rate(rate: float) -> None:
    """Imposta il tasso risk-free costante."""
    global _risk_free_rate
    _risk_free_rate = rate


def set_risk_free_series(series: pd.Series) -> None:
    """Imposta una serie storica di tassi risk-free.

    La serie deve avere un DatetimeIndex e valori annualizzati.
    """
    global _risk_free_series
    _risk_free_series = series.sort_index()


def clear_risk_free_series() -> None:
    """Rimuove la serie storica, tornando al valore costante."""
    global _risk_free_series
    _risk_free_series = None
