"""
Strategie nel tempo (Fase 5).

Simula il valore di un portafoglio nel tempo sui prezzi storici,
applicando diversi tipi di ribilanciamento e costi di transazione.

Tre strategie (interfaccia comune + registry):
1. Buy & Hold: investi all'inizio, poi lasci correre
2. Ribilanciamento periodico: riporta ai pesi target a frequenza fissa
3. Ribilanciamento a soglia: ribilancia solo se un peso devia oltre la soglia

OUTPUT (contratto per le fasi successive):
    StrategyResult con:
    - portfolio_value: pd.Series, valore del portafoglio nel tempo
    - weights_history: pd.DataFrame, pesi giornalieri per ticker
    - metrics: dict con CAGR, volatilità, max drawdown, Sharpe, ecc.
    - rebalance_log: lista di date e dettagli di ogni ribilanciamento
    - metadata: tipo strategia, parametri, costi
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from .config import get_risk_free_rate

logger = logging.getLogger(__name__)

# Costo di transazione di default: 10 bps (0.10%) sul nozionale scambiato
DEFAULT_TX_COST_BPS = 10
ANN_FACTOR = 252  # Business days per anno


@dataclass
class RebalanceEvent:
    """Registrazione di un singolo ribilanciamento."""
    date: date
    turnover: float      # Quota di portafoglio scambiata (somma |delta_w|)
    cost: float          # Costo in unità di portafoglio
    weights_before: dict[str, float]
    weights_after: dict[str, float]


@dataclass
class StrategyResult:
    """Contratto di output della Fase 5.

    Questo oggetto sarà l'input delle fasi successive (reportistica).
    """
    portfolio_value: pd.Series     # Valore del portafoglio, index=date
    weights_history: pd.DataFrame  # Pesi giornalieri, colonne=ticker
    metrics: dict[str, float]      # CAGR, vol, max_dd, sharpe, ecc.
    rebalance_log: list[RebalanceEvent]
    metadata: dict = field(default_factory=dict)


def compute_metrics(
    portfolio_value: pd.Series,
    rebalance_log: list[RebalanceEvent],
    ann_factor: int = ANN_FACTOR,
) -> dict[str, float]:
    """Calcola le metriche di performance.

    Metriche:
    - total_return: rendimento totale
    - cagr: rendimento annualizzato composto
    - volatility: volatilità annualizzata dei rendimenti giornalieri
    - max_drawdown: massimo drawdown (negativo)
    - sharpe: Sharpe ratio annualizzato (usa il risk-free centralizzato da get_risk_free_rate())
    - n_rebalances: numero di ribilanciamenti
    - total_turnover: turnover cumulato
    - total_costs: costi cumulati
    """
    pv = portfolio_value.dropna()
    if len(pv) < 2:
        return {k: 0.0 for k in [
            "total_return", "cagr", "volatility", "max_drawdown",
            "sharpe", "n_rebalances", "total_turnover", "total_costs",
        ]}

    # Rendimenti giornalieri
    daily_returns = pv.pct_change().dropna()

    # Rendimento totale
    total_return = pv.iloc[-1] / pv.iloc[0] - 1

    # CAGR: (V_final / V_initial)^(ann_factor / n_days) - 1
    n_days = len(pv) - 1
    if n_days > 0 and pv.iloc[0] > 0:
        cagr = (pv.iloc[-1] / pv.iloc[0]) ** (ann_factor / n_days) - 1
    else:
        cagr = 0.0

    # Volatilità annualizzata
    vol = daily_returns.std() * np.sqrt(ann_factor)

    # Max drawdown
    cummax = pv.cummax()
    drawdown = (pv - cummax) / cummax
    max_dd = drawdown.min()

    # Sharpe (usa il risk-free centralizzato)
    rf = get_risk_free_rate()
    sharpe = (cagr - rf) / vol if vol > 1e-10 else 0.0

    # Costi e turnover
    total_turnover = sum(e.turnover for e in rebalance_log)
    total_costs = sum(e.cost for e in rebalance_log)

    return {
        "total_return": float(total_return),
        "cagr": float(cagr),
        "volatility": float(vol),
        "max_drawdown": float(max_dd),
        "sharpe": float(sharpe),
        "n_rebalances": len(rebalance_log),
        "total_turnover": float(total_turnover),
        "total_costs": float(total_costs),
    }


def _evolve_weights(weights: np.ndarray, daily_returns: np.ndarray) -> np.ndarray:
    """Evolve i pesi di un giorno in base ai rendimenti.

    w_new[i] = w_old[i] * (1 + r[i]) / sum(w_old * (1 + r))
    """
    growth = weights * (1 + daily_returns)
    total = growth.sum()
    if total <= 0:
        return weights  # Evita divisioni per zero
    return growth / total


def simulate(
    prices: pd.DataFrame,
    target_weights: dict[str, float],
    strategy: "Strategy",
    initial_capital: float = 100.0,
    tx_cost_bps: float = DEFAULT_TX_COST_BPS,
) -> StrategyResult:
    """Simula la strategia sui prezzi storici.

    Parametri:
        prices: prezzi puliti in EUR (Fase 1), colonne = ticker
        target_weights: pesi obiettivo (da ProfileResult)
        strategy: strategia di ribilanciamento
        initial_capital: capitale iniziale
        tx_cost_bps: costo di transazione in basis points

    Nota anti-lookahead: il target è fissato PRIMA della simulazione,
    calcolato sui dati fino alla data di partenza.
    """
    tx_cost_frac = tx_cost_bps / 10_000

    # Filtra solo i ticker presenti nei pesi target
    tickers = [t for t in target_weights if t in prices.columns]
    if not tickers:
        raise ValueError("Nessun ticker in comune tra target_weights e prices")

    target_w = np.array([target_weights[t] for t in tickers])
    # Normalizza i pesi target (nel caso alcuni ticker manchino)
    if target_w.sum() > 0:
        target_w = target_w / target_w.sum()

    price_data = prices[tickers]
    returns = price_data.pct_change()
    dates = price_data.index

    # Array per i risultati
    n_dates = len(dates)
    weights_hist = np.zeros((n_dates, len(tickers)))
    pv = np.zeros(n_dates)
    rebalance_log: list[RebalanceEvent] = []

    # Giorno 0: investo al target (costo iniziale di acquisto incluso)
    current_w = target_w.copy()
    initial_turnover = target_w.sum()  # Tutto il capitale investito
    initial_cost = initial_capital * initial_turnover * tx_cost_frac
    capital = initial_capital - initial_cost

    rebalance_log.append(RebalanceEvent(
        date=dates[0].date(),
        turnover=float(initial_turnover),
        cost=float(initial_cost),
        weights_before={t: 0.0 for t in tickers},
        weights_after={t: float(target_w[i]) for i, t in enumerate(tickers)},
    ))

    pv[0] = capital
    weights_hist[0] = current_w

    # Simulazione giorno per giorno
    for t in range(1, n_dates):
        daily_ret = returns.iloc[t].values

        # Gestisci NaN nei rendimenti (es. strumento non quotato quel giorno)
        daily_ret = np.nan_to_num(daily_ret, nan=0.0)

        # Evolvi i pesi col mercato
        current_w = _evolve_weights(current_w, daily_ret)

        # Aggiorna il valore del portafoglio
        port_return = np.dot(weights_hist[t - 1], daily_ret)
        pv[t] = pv[t - 1] * (1 + port_return)

        # Chiedi alla strategia se ribilanciare
        if strategy.should_rebalance(t, dates[t], current_w, target_w):
            # Calcola turnover e costo
            turnover = float(np.abs(current_w - target_w).sum())
            cost = pv[t] * turnover * tx_cost_frac
            pv[t] -= cost

            rebalance_log.append(RebalanceEvent(
                date=dates[t].date(),
                turnover=turnover,
                cost=float(cost),
                weights_before={tk: float(current_w[i]) for i, tk in enumerate(tickers)},
                weights_after={tk: float(target_w[i]) for i, tk in enumerate(tickers)},
            ))

            current_w = target_w.copy()

        weights_hist[t] = current_w

    # Costruisci output
    pv_series = pd.Series(pv, index=dates, name="portfolio_value")
    wh_df = pd.DataFrame(weights_hist, index=dates, columns=tickers)
    metrics = compute_metrics(pv_series, rebalance_log)

    metadata = {
        "strategy": strategy.name,
        "strategy_params": strategy.params,
        "initial_capital": initial_capital,
        "tx_cost_bps": tx_cost_bps,
        "tickers": tickers,
        "target_weights": {t: float(target_w[i]) for i, t in enumerate(tickers)},
        "n_days": n_dates,
    }

    logger.info(
        f"Simulazione {strategy.name}: {n_dates} giorni, "
        f"{metrics['n_rebalances']} ribilanciamenti, "
        f"CAGR={metrics['cagr']:.2%}, MaxDD={metrics['max_drawdown']:.2%}"
    )

    return StrategyResult(
        portfolio_value=pv_series,
        weights_history=wh_df,
        metrics=metrics,
        rebalance_log=rebalance_log,
        metadata=metadata,
    )


# ============================================================
# Interfaccia e implementazioni delle strategie
# ============================================================

class Strategy(ABC):
    """Interfaccia astratta per le strategie di ribilanciamento."""

    @abstractmethod
    def should_rebalance(
        self,
        day_index: int,
        current_date: pd.Timestamp,
        current_weights: np.ndarray,
        target_weights: np.ndarray,
    ) -> bool:
        """Decide se ribilanciare in questa data."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @property
    @abstractmethod
    def params(self) -> dict:
        ...


class BuyAndHold(Strategy):
    """Buy & Hold: investi all'inizio, poi non fare nulla."""

    @property
    def name(self) -> str:
        return "buy_and_hold"

    @property
    def params(self) -> dict:
        return {}

    def should_rebalance(self, day_index, current_date, current_weights, target_weights):
        # Mai ribilanciare (l'acquisto iniziale è gestito da simulate())
        return False


class PeriodicRebalance(Strategy):
    """Ribilanciamento a frequenza fissa.

    Frequenze supportate: monthly, quarterly, annual.
    """

    def __init__(self, frequency: str = "quarterly"):
        if frequency not in ("monthly", "quarterly", "annual"):
            raise ValueError(f"Frequenza non supportata: {frequency}")
        self._frequency = frequency
        self._last_rebalance_month: int | None = None
        self._last_rebalance_year: int | None = None

    @property
    def name(self) -> str:
        return "periodic"

    @property
    def params(self) -> dict:
        return {"frequency": self._frequency}

    def should_rebalance(self, day_index, current_date, current_weights, target_weights):
        # Giorno 0 è gestito da simulate(), non ribilanciamo
        if day_index == 0:
            return False

        month = current_date.month
        year = current_date.year

        if self._frequency == "monthly":
            trigger = (month != self._last_rebalance_month)
        elif self._frequency == "quarterly":
            # Ribilancia al cambio di trimestre (mesi 1,4,7,10)
            quarter = (month - 1) // 3
            last_quarter = ((self._last_rebalance_month or 0) - 1) // 3
            trigger = (quarter != last_quarter) or (year != self._last_rebalance_year)
        else:  # annual
            trigger = (year != self._last_rebalance_year)

        if trigger:
            self._last_rebalance_month = month
            self._last_rebalance_year = year

        return trigger


class ThresholdRebalance(Strategy):
    """Ribilanciamento a soglia: ribilancia solo se un peso devia
    dal target oltre la soglia (in punti percentuali assoluti).

    Default: ±5pp (0.05).
    """

    def __init__(self, threshold: float = 0.05):
        self._threshold = threshold

    @property
    def name(self) -> str:
        return "threshold"

    @property
    def params(self) -> dict:
        return {"threshold": self._threshold}

    def should_rebalance(self, day_index, current_date, current_weights, target_weights):
        if day_index == 0:
            return False
        # Ribilancia se QUALUNQUE peso devia dal target oltre la soglia
        max_deviation = np.max(np.abs(current_weights - target_weights))
        return max_deviation > self._threshold


# ============================================================
# Registry
# ============================================================

STRATEGIES: dict[str, type[Strategy]] = {
    "buy_and_hold": BuyAndHold,
    "periodic": PeriodicRebalance,
    "threshold": ThresholdRebalance,
}


def get_strategy(name: str, **kwargs) -> Strategy:
    """Restituisce un'istanza della strategia per nome."""
    if name not in STRATEGIES:
        raise ValueError(
            f"Strategia '{name}' non trovata. Disponibili: {list(STRATEGIES.keys())}"
        )
    return STRATEGIES[name](**kwargs)
