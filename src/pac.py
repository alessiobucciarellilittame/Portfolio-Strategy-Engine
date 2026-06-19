"""
Modalita' PAC — Piano di Accumulo del Capitale.

Simula l'investimento periodico di un importo fisso a intervalli regolari,
anziche' un investimento in somma unica al giorno zero.

L'allocazione (pesi target) viene SEMPRE dal motore esistente (profili /
core-satellite). Il PAC cambia solo QUANDO entrano i soldi.

Funzionalita':
- simulate_pac: simulazione PAC con costi reali (Fase 8)
- compute_pac_metrics: metriche specifiche (IRR, TWR, max drawdown)
- compare_pac_vs_lumpsum: confronto diretto sullo stesso periodo e totale

Costi di transazione reali applicati a OGNI versamento:
spread per asset class + commissione broker con minimo fisso.
Con versamenti piccoli la commissione minima pesa molto: e' un dato
informativo fondamentale del PAC.
"""

import logging
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd
from scipy.optimize import brentq

from .config import get_risk_free_rate
from .costs import (
    compute_tx_cost_for_trade,
    load_costs_config,
    DEFAULT_CAPITAL_EUR,
)
from .strategies import (
    simulate,
    StrategyResult,
    RebalanceEvent,
    _evolve_weights,
    Strategy,
    ANN_FACTOR,
)

logger = logging.getLogger(__name__)

# Frequenze PAC supportate
PAC_FREQUENCIES = {
    "monthly": "MS",       # Primo giorno lavorativo del mese
    "quarterly": "QS",     # Primo giorno lavorativo del trimestre
    "annual": "YS",        # Primo giorno lavorativo dell'anno
}


@dataclass
class PacCashflow:
    """Singolo versamento PAC."""
    date: date
    amount: float          # Importo versato (EUR)
    spread_cost: float     # Costo spread
    commission_cost: float # Commissione broker
    total_cost: float      # spread + commissione
    portfolio_value_after: float  # Valore portafoglio dopo il versamento


@dataclass
class PacResult:
    """Risultato della simulazione PAC.

    Contratto di output: contiene tutto per metriche, confronto e dashboard.
    """
    portfolio_value: pd.Series      # Valore portafoglio giornaliero
    weights_history: pd.DataFrame   # Pesi giornalieri
    cashflows: list[PacCashflow]    # Dettaglio versamenti
    rebalance_log: list[RebalanceEvent]  # Log ribilanciamenti
    metrics: dict[str, float]       # IRR, TWR, max_dd, ecc.
    metadata: dict = field(default_factory=dict)


@dataclass
class PacComparison:
    """Confronto PAC vs somma unica sullo stesso periodo e totale."""
    pac: PacResult
    lumpsum: StrategyResult
    total_invested: float           # Totale versato (uguale per entrambi)
    period_start: date
    period_end: date
    summary: dict[str, dict[str, float]]  # {"pac": {...}, "lumpsum": {...}}


def _find_contribution_dates(
    price_index: pd.DatetimeIndex,
    frequency: str,
) -> list[pd.Timestamp]:
    """Trova le date di versamento PAC all'interno dell'indice prezzi.

    Per ogni periodo (mese/trimestre/anno) trova il primo giorno di
    trading disponibile nell'indice.
    """
    freq_code = PAC_FREQUENCIES.get(frequency)
    if freq_code is None:
        raise ValueError(
            f"Frequenza PAC '{frequency}' non supportata. "
            f"Disponibili: {list(PAC_FREQUENCIES.keys())}"
        )

    start = price_index[0]
    end = price_index[-1]

    # Genera date teoriche. Partiamo da un periodo prima per catturare
    # il primo periodo che contiene start.
    theoretical = pd.date_range(start=start, end=end, freq=freq_code)

    # Se nessuna data teorica cade nel range (es. dati tutti nello stesso anno
    # per frequenza annuale), il primo giorno di trading e' il primo versamento.
    if len(theoretical) == 0:
        return [start]

    # Per ogni data teorica, trova la prima data di trading >= a essa
    contribution_dates = []
    for td in theoretical:
        candidates = price_index[price_index >= td]
        if len(candidates) > 0:
            contribution_dates.append(candidates[0])

    # Rimuovi duplicati (puo' succedere ai bordi)
    seen = set()
    unique = []
    for d in contribution_dates:
        if d not in seen:
            seen.add(d)
            unique.append(d)

    return unique


def compute_irr(
    cashflow_dates: list[date],
    cashflow_amounts: list[float],
    final_value: float,
    final_date: date,
) -> float:
    """Calcola l'IRR (Internal Rate of Return) money-weighted.

    Convenzione: versamenti negativi (esborso), valore finale positivo.
    Risolve il tasso annuo r tale che:
        sum_i( CF_i / (1+r)^t_i ) + FV / (1+r)^T = 0

    Usa scipy.optimize.brentq per la ricerca della radice.
    Restituisce il tasso annuo (es. 0.05 = 5%).
    """
    if not cashflow_dates or final_value <= 0:
        return 0.0

    # Converti date in frazioni d'anno dal primo versamento
    base_date = cashflow_dates[0]
    year_fracs = []
    amounts = []
    for d, a in zip(cashflow_dates, cashflow_amounts):
        delta = (d - base_date).days / 365.25
        year_fracs.append(delta)
        amounts.append(-abs(a))  # Versamenti sono negativi

    # Aggiungi il valore finale come flusso positivo
    final_frac = (final_date - base_date).days / 365.25
    year_fracs.append(final_frac)
    amounts.append(final_value)

    def npv(r):
        total = 0.0
        for t, cf in zip(year_fracs, amounts):
            total += cf / (1 + r) ** t
        return total

    # Cerca la radice in un intervallo ragionevole
    try:
        irr = brentq(npv, -0.50, 5.0, xtol=1e-10, maxiter=1000)
    except ValueError:
        # Se non trova la radice nell'intervallo, prova piu' ampio
        try:
            irr = brentq(npv, -0.99, 10.0, xtol=1e-10, maxiter=1000)
        except ValueError:
            logger.warning("IRR non calcolabile: nessuna radice trovata.")
            irr = 0.0

    return float(irr)


def simulate_pac(
    prices: pd.DataFrame,
    target_weights: dict[str, float],
    strategy: Strategy,
    contribution: float,
    frequency: str = "monthly",
    initial_capital: float = 0.0,
    asset_class_map: dict[str, str] | None = None,
    costs_config: dict | None = None,
) -> PacResult:
    """Simula un Piano di Accumulo del Capitale.

    Parametri:
        prices: prezzi puliti in EUR (Fase 1), colonne = ticker
        target_weights: pesi obiettivo (da ProfileResult / core-satellite)
        strategy: strategia di ribilanciamento (riusa quelle esistenti)
        contribution: importo fisso di ogni versamento (EUR)
        frequency: "monthly", "quarterly", "annual"
        initial_capital: versamento iniziale opzionale (default 0)
        asset_class_map: ticker -> asset class (per costi reali).
                         Se None, tutti trattati come "equity".
        costs_config: configurazione costi da YAML. Se None, caricata da file.

    Costi applicati a ogni versamento:
    - Spread bid-ask per asset class
    - Commissione broker con minimo fisso (pesa molto su versamenti piccoli)
    """
    if costs_config is None:
        costs_config = load_costs_config()
    if asset_class_map is None:
        asset_class_map = {}

    # Filtra ticker presenti
    tickers = [t for t in target_weights if t in prices.columns]
    if not tickers:
        raise ValueError("Nessun ticker in comune tra target_weights e prices")

    target_w = np.array([target_weights[t] for t in tickers])
    if target_w.sum() > 0:
        target_w = target_w / target_w.sum()

    price_data = prices[tickers]
    returns = price_data.pct_change()
    dates = price_data.index
    n_dates = len(dates)

    # Date di versamento
    contribution_dates = _find_contribution_dates(dates, frequency)
    contribution_set = set(contribution_dates)

    # Turnover per ticker quando si investe al target (acquisto completo)
    turnover_full = {t: float(target_w[i]) for i, t in enumerate(tickers)}

    # Stato della simulazione
    current_w = target_w.copy()
    portfolio_value = 0.0
    holdings_value = np.zeros(len(tickers))  # Valore per ticker in EUR

    weights_hist = np.zeros((n_dates, len(tickers)))
    pv = np.zeros(n_dates)
    rebalance_log: list[RebalanceEvent] = []
    cashflows: list[PacCashflow] = []

    # Reset stato strategia per il PAC
    if hasattr(strategy, '_last_rebalance_month'):
        strategy._last_rebalance_month = None
        strategy._last_rebalance_year = None

    for t in range(n_dates):
        current_date = dates[t]

        # 1. Evolvi il portafoglio col mercato (se non e' il giorno 0)
        if t > 0:
            daily_ret = returns.iloc[t].values
            daily_ret = np.nan_to_num(daily_ret, nan=0.0)

            # Aggiorna il valore delle posizioni
            holdings_value = holdings_value * (1 + daily_ret)
            portfolio_value = holdings_value.sum()

            # Aggiorna i pesi
            if portfolio_value > 0:
                current_w = holdings_value / portfolio_value
            # else: pesi restano quelli precedenti

        # 2. Versamento PAC
        is_contribution_day = current_date in contribution_set
        amount_to_invest = 0.0

        if t == 0 and initial_capital > 0:
            amount_to_invest = initial_capital
        if is_contribution_day:
            amount_to_invest += contribution

        if amount_to_invest > 0:
            # Calcola costi di transazione reali
            # Il turnover e' sull'intero importo versato (tutto investito al target)
            spread_cost, commission_cost = compute_tx_cost_for_trade(
                turnover_full, amount_to_invest, asset_class_map, costs_config,
            )
            total_cost = spread_cost + commission_cost
            net_amount = amount_to_invest - total_cost

            if net_amount > 0:
                # Investi al target
                new_holdings = target_w * net_amount
                holdings_value = holdings_value + new_holdings
                portfolio_value = holdings_value.sum()
                if portfolio_value > 0:
                    current_w = holdings_value / portfolio_value

            cashflows.append(PacCashflow(
                date=current_date.date(),
                amount=amount_to_invest,
                spread_cost=spread_cost,
                commission_cost=commission_cost,
                total_cost=total_cost,
                portfolio_value_after=portfolio_value,
            ))

            rebalance_log.append(RebalanceEvent(
                date=current_date.date(),
                turnover=float(target_w.sum()),
                cost=float(total_cost),
                weights_before={tk: 0.0 for tk in tickers} if t == 0 and initial_capital == 0
                    else {tk: float(current_w[i]) for i, tk in enumerate(tickers)},
                weights_after={tk: float(target_w[i]) for i, tk in enumerate(tickers)},
            ))

        # 3. Ribilanciamento (se la strategia lo richiede e non e' un giorno di versamento)
        elif t > 0 and portfolio_value > 0:
            if strategy.should_rebalance(t, current_date, current_w, target_w):
                # Calcola turnover e costi del ribilanciamento
                delta_w = {tk: float(abs(current_w[i] - target_w[i]))
                          for i, tk in enumerate(tickers)}
                spread_cost, commission_cost = compute_tx_cost_for_trade(
                    delta_w, portfolio_value, asset_class_map, costs_config,
                )
                total_cost = spread_cost + commission_cost

                turnover = float(np.abs(current_w - target_w).sum())

                rebalance_log.append(RebalanceEvent(
                    date=current_date.date(),
                    turnover=turnover,
                    cost=float(total_cost),
                    weights_before={tk: float(current_w[i]) for i, tk in enumerate(tickers)},
                    weights_after={tk: float(target_w[i]) for i, tk in enumerate(tickers)},
                ))

                # Applica il costo e ribilancia
                portfolio_value -= total_cost
                if portfolio_value > 0:
                    holdings_value = target_w * portfolio_value
                    current_w = target_w.copy()

        pv[t] = portfolio_value
        weights_hist[t] = current_w if portfolio_value > 0 else target_w

    # Costruisci output
    pv_series = pd.Series(pv, index=dates, name="portfolio_value")
    wh_df = pd.DataFrame(weights_hist, index=dates, columns=tickers)

    # Metriche PAC
    metrics = compute_pac_metrics(pv_series, cashflows)

    metadata = {
        "strategy": strategy.name,
        "strategy_params": strategy.params,
        "contribution": contribution,
        "frequency": frequency,
        "initial_capital": initial_capital,
        "n_contributions": len(cashflows),
        "tickers": tickers,
        "target_weights": {t: float(target_w[i]) for i, t in enumerate(tickers)},
        "n_days": n_dates,
    }

    logger.info(
        f"PAC {frequency}: {len(cashflows)} versamenti x {contribution:.0f} EUR, "
        f"totale versato {metrics['total_invested']:.0f} EUR, "
        f"valore finale {metrics['final_value']:.0f} EUR, "
        f"IRR={metrics['irr']:.2%}"
    )

    return PacResult(
        portfolio_value=pv_series,
        weights_history=wh_df,
        cashflows=cashflows,
        rebalance_log=rebalance_log,
        metrics=metrics,
        metadata=metadata,
    )


def compute_pac_metrics(
    portfolio_value: pd.Series,
    cashflows: list[PacCashflow],
) -> dict[str, float]:
    """Calcola le metriche specifiche del PAC.

    Metriche:
    - total_invested: somma di tutti i versamenti
    - total_costs: somma di tutti i costi di transazione
    - final_value: valore finale del portafoglio
    - absolute_gain: valore finale - totale versato
    - gain_pct: guadagno percentuale sul totale versato
    - irr: rendimento money-weighted (tasso annuo)
    - twr: rendimento time-weighted (per confronto con somma unica)
    - max_drawdown: massimo drawdown della curva di valore
    - n_contributions: numero di versamenti
    - avg_cost_pct: costo medio percentuale per versamento
    """
    total_invested = sum(cf.amount for cf in cashflows)
    total_costs = sum(cf.total_cost for cf in cashflows)
    final_value = float(portfolio_value.iloc[-1]) if len(portfolio_value) > 0 else 0.0

    absolute_gain = final_value - total_invested
    gain_pct = absolute_gain / total_invested if total_invested > 0 else 0.0

    # IRR
    cf_dates = [cf.date for cf in cashflows]
    cf_amounts = [cf.amount for cf in cashflows]
    final_date = portfolio_value.index[-1].date() if len(portfolio_value) > 0 else cf_dates[-1] if cf_dates else date.today()

    irr = compute_irr(cf_dates, cf_amounts, final_value, final_date)

    # TWR (time-weighted return): usa i rendimenti giornalieri
    pv = portfolio_value.dropna()
    # Filtra solo i giorni in cui il portafoglio ha valore > 0
    pv_positive = pv[pv > 0]
    if len(pv_positive) >= 2:
        # TWR: prodotto dei rendimenti giornalieri escludendo i giorni di versamento
        # Approssimazione: CAGR della serie (ignora i flussi)
        n_days = len(pv_positive) - 1
        twr = (pv_positive.iloc[-1] / pv_positive.iloc[0]) ** (ANN_FACTOR / n_days) - 1
    else:
        twr = 0.0

    # Max drawdown (calcolato sulla parte con valore > 0)
    if len(pv_positive) >= 2:
        cummax = pv_positive.cummax()
        drawdown = (pv_positive - cummax) / cummax
        max_dd = float(drawdown.min())
    else:
        max_dd = 0.0

    # Costo medio percentuale per versamento
    avg_cost_pct = (total_costs / total_invested) if total_invested > 0 else 0.0

    return {
        "total_invested": float(total_invested),
        "total_costs": float(total_costs),
        "final_value": float(final_value),
        "absolute_gain": float(absolute_gain),
        "gain_pct": float(gain_pct),
        "irr": float(irr),
        "twr": float(twr),
        "max_drawdown": float(max_dd),
        "n_contributions": len(cashflows),
        "avg_cost_pct": float(avg_cost_pct),
    }


def compare_pac_vs_lumpsum(
    prices: pd.DataFrame,
    target_weights: dict[str, float],
    strategy: Strategy,
    contribution: float,
    frequency: str = "monthly",
    initial_capital: float = 0.0,
    asset_class_map: dict[str, str] | None = None,
    costs_config: dict | None = None,
) -> PacComparison:
    """Confronto diretto PAC vs somma unica sullo stesso periodo.

    Il totale investito e' identico: la somma unica investe al giorno zero
    l'intero ammontare che il PAC versa nel tempo.

    Parametri: stessi di simulate_pac.
    """
    # 1. Simula PAC
    pac_result = simulate_pac(
        prices, target_weights, strategy,
        contribution=contribution,
        frequency=frequency,
        initial_capital=initial_capital,
        asset_class_map=asset_class_map,
        costs_config=costs_config,
    )

    total_invested = pac_result.metrics["total_invested"]

    # 2. Simula somma unica con lo stesso totale
    # Usa simulate() originale con tx_cost_bps=0 e poi applica i costi
    # reali al solo acquisto iniziale per coerenza
    lumpsum_result = simulate(
        prices, target_weights, strategy,
        initial_capital=total_invested,
        tx_cost_bps=0,
    )

    # Applica i costi reali all'acquisto iniziale della somma unica
    if costs_config is None:
        costs_config = load_costs_config()
    if asset_class_map is None:
        asset_class_map = {}

    tickers = [t for t in target_weights if t in prices.columns]
    target_w_arr = np.array([target_weights[t] for t in tickers])
    if target_w_arr.sum() > 0:
        target_w_arr = target_w_arr / target_w_arr.sum()
    turnover_full = {t: float(target_w_arr[i]) for i, t in enumerate(tickers)}

    spread_cost, commission_cost = compute_tx_cost_for_trade(
        turnover_full, total_invested, asset_class_map, costs_config,
    )
    initial_tx_cost = spread_cost + commission_cost

    # Scala la equity curve della somma unica per riflettere il costo iniziale
    cost_ratio = 1 - initial_tx_cost / total_invested if total_invested > 0 else 1.0
    adjusted_pv = lumpsum_result.portfolio_value * cost_ratio
    lumpsum_result = StrategyResult(
        portfolio_value=adjusted_pv,
        weights_history=lumpsum_result.weights_history,
        metrics=lumpsum_result.metrics.copy(),
        rebalance_log=lumpsum_result.rebalance_log,
        metadata=lumpsum_result.metadata.copy(),
    )
    # Ricalcola le metriche sulla curva aggiustata
    from .strategies import compute_metrics
    lumpsum_result.metrics = compute_metrics(adjusted_pv, lumpsum_result.rebalance_log)
    lumpsum_result.metadata["initial_capital"] = total_invested
    lumpsum_result.metadata["initial_tx_cost"] = initial_tx_cost

    # 3. Costruisci il riepilogo
    pac_m = pac_result.metrics
    ls_m = lumpsum_result.metrics

    period_start = prices.index[0].date()
    period_end = prices.index[-1].date()

    summary = {
        "pac": {
            "total_invested": pac_m["total_invested"],
            "final_value": pac_m["final_value"],
            "absolute_gain": pac_m["absolute_gain"],
            "irr": pac_m["irr"],
            "twr": pac_m["twr"],
            "max_drawdown": pac_m["max_drawdown"],
            "total_costs": pac_m["total_costs"],
        },
        "lumpsum": {
            "total_invested": total_invested,
            "final_value": float(adjusted_pv.iloc[-1]),
            "absolute_gain": float(adjusted_pv.iloc[-1]) - total_invested,
            "cagr": ls_m["cagr"],
            "max_drawdown": ls_m["max_drawdown"],
            "total_costs": initial_tx_cost,
        },
    }

    return PacComparison(
        pac=pac_result,
        lumpsum=lumpsum_result,
        total_invested=total_invested,
        period_start=period_start,
        period_end=period_end,
        summary=summary,
    )
