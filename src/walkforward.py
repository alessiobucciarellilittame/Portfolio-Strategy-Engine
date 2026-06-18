"""
Backtest walk-forward (Fase 6).

Ri-stima mu/Sigma e ri-ottimizza il portafoglio a ogni data di ribilanciamento,
simulando cio' che si sarebbe fatto realmente in passato.

A ogni data di ribilanciamento T:
1. Stima mu/Sigma usando SOLO dati con data < T (anti-lookahead)
2. Ottimizza con vincoli del profilo -> nuovi pesi target
3. Applica costi di transazione sul turnover
4. Registra i rendimenti realizzati fino al ribilanciamento successivo

OUTPUT (contratto):
    WalkForwardResult con:
    - portfolio_value: pd.Series, equity curve out-of-sample
    - weights_history: pd.DataFrame, pesi giornalieri
    - target_weights_history: pd.DataFrame, pesi target a ogni ribilanciamento
    - metrics: dict con CAGR, vol, max_dd, sharpe, n_rebalances, costi
    - rebalance_log: lista di RebalanceEvent
    - validation_warnings: lista di avvisi
    - metadata: configurazione del backtest
"""

import logging
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from .estimation import estimate_parameters
from .profiles import ProfileConfig, build_portfolio_for_profile
from .strategies import RebalanceEvent, compute_metrics, _evolve_weights

logger = logging.getLogger(__name__)

SUSPICIOUS_SHARPE = 2.5
MAX_WEIGHT_CHANGE_WARN = 0.30  # Avviso se un peso target cambia di >30pp


@dataclass
class WalkForwardResult:
    """Contratto di output della Fase 6.

    Questo oggetto contiene l'equity curve out-of-sample, i pesi nel tempo,
    le metriche di performance e la sequenza dei target nel tempo.
    """
    portfolio_value: pd.Series
    weights_history: pd.DataFrame
    target_weights_history: pd.DataFrame
    metrics: dict[str, float]
    rebalance_log: list[RebalanceEvent]
    validation_warnings: list[str]
    metadata: dict = field(default_factory=dict)


def _generate_rebalance_dates(
    dates: pd.DatetimeIndex,
    frequency: str,
) -> list[pd.Timestamp]:
    """Genera le date di ribilanciamento dall'indice dei prezzi.

    La prima data e' sempre inclusa (investimento iniziale).
    Le successive scattano al cambio di mese/trimestre/anno.
    """
    if len(dates) == 0:
        return []

    if frequency not in ("monthly", "quarterly", "annual"):
        raise ValueError(f"Frequenza non supportata: {frequency}")

    result = [dates[0]]
    last_month = dates[0].month
    last_year = dates[0].year

    for d in dates[1:]:
        trigger = False
        if frequency == "monthly":
            trigger = d.month != last_month
        elif frequency == "quarterly":
            q = (d.month - 1) // 3
            lq = (last_month - 1) // 3
            trigger = (q != lq) or (d.year != last_year)
        elif frequency == "annual":
            trigger = d.year != last_year

        if trigger:
            result.append(d)
            last_month = d.month
            last_year = d.year

    return result


def decide_weights(
    returns: pd.DataFrame,
    as_of: date,
    profile: ProfileConfig,
    asset_class_map: dict[str, str],
    horizon_years: int = 5,
    mean_method: str = "bayes_stein",
    cov_method: str = "ledoit_wolf",
    window_type: str = "rolling",
    window_days: int | None = 756,
) -> tuple[dict[str, float] | None, list[str]]:
    """Decide i pesi target usando SOLO dati con data < as_of.

    ANTI-LOOKAHEAD: taglia i rendimenti a date strettamente precedenti
    a as_of prima di qualunque calcolo. E' strutturalmente impossibile
    che dati futuri influenzino la decisione.

    Parametri:
        returns: rendimenti completi (tutta la storia disponibile)
        as_of: data della decisione (i dati di questa data NON sono usati)
        profile: configurazione del profilo investitore
        asset_class_map: ticker -> asset class
        horizon_years: orizzonte investitore
        mean_method: stimatore mu
        cov_method: stimatore covarianza
        window_type: "rolling" o "expanding"
        window_days: finestra rolling in giorni di trading (solo per rolling)

    Restituisce:
        (weights_dict, validation_issues) o (None, issues) se infeasible.
    """
    # ANTI-LOOKAHEAD: cutoff a as_of - 1 giorno (strettamente < as_of)
    # prepare_returns usa loc[:as_of] che e' inclusivo, quindi passiamo il giorno prima
    cutoff = pd.Timestamp(as_of) - pd.Timedelta(days=1)

    effective_window = window_days if window_type == "rolling" else None

    try:
        params = estimate_parameters(
            returns,
            mean_method=mean_method,
            cov_method=cov_method,
            as_of=cutoff.date(),
            window_days=effective_window,
        )

        result = build_portfolio_for_profile(
            profile, params,
            horizon_years=horizon_years,
            asset_class_map=asset_class_map,
        )

        if not result.portfolio.is_feasible():
            return None, result.validation_issues

        return result.portfolio.weights, result.validation_issues

    except Exception as e:
        logger.error(f"Errore decisione pesi a {as_of}: {e}")
        return None, [str(e)]


def run_walkforward(
    prices: pd.DataFrame,
    returns: pd.DataFrame,
    profile: ProfileConfig,
    asset_class_map: dict[str, str],
    sim_start: date,
    sim_end: date,
    frequency: str = "quarterly",
    horizon_years: int = 5,
    mean_method: str = "bayes_stein",
    cov_method: str = "ledoit_wolf",
    window_type: str = "rolling",
    window_days: int | None = 756,
    initial_capital: float = 100.0,
    tx_cost_bps: float = 10,
) -> WalkForwardResult:
    """Esegue il backtest walk-forward.

    Parametri:
        prices: prezzi completi (la storia pre-simulazione serve per
                avere i prezzi di partenza; viene tagliata a sim_start:sim_end)
        returns: rendimenti completi (tutta la storia, per la stima parametri)
        profile: configurazione del profilo investitore
        asset_class_map: ticker -> asset class
        sim_start: data inizio simulazione
        sim_end: data fine simulazione
        frequency: frequenza ribilanciamento ("monthly", "quarterly", "annual")
        horizon_years: orizzonte investitore
        mean_method: stimatore mu
        cov_method: stimatore covarianza
        window_type: "rolling" o "expanding"
        window_days: finestra rolling in giorni di trading (~3y = 756)
        initial_capital: capitale iniziale
        tx_cost_bps: costi di transazione in basis points
    """
    tx_cost_frac = tx_cost_bps / 10_000

    # Slice prices to simulation period
    sim_prices = prices.loc[pd.Timestamp(sim_start):pd.Timestamp(sim_end)]
    dates = sim_prices.index
    n_dates = len(dates)

    if n_dates < 2:
        raise ValueError(f"Periodo simulazione troppo corto: {n_dates} giorni")

    tickers = list(sim_prices.columns)
    n_tickers = len(tickers)
    daily_returns = sim_prices.pct_change()

    # Generate rebalance dates
    rebalance_dates = _generate_rebalance_dates(dates, frequency)
    rebalance_set = set(rebalance_dates)

    logger.info(
        f"Walk-forward: {n_dates} giorni, "
        f"{len(rebalance_dates)} ribilanciamenti pianificati, "
        f"frequenza={frequency}, window={window_type}({window_days})"
    )

    # Storage
    weights_hist = np.zeros((n_dates, n_tickers))
    pv = np.zeros(n_dates)
    rebalance_log: list[RebalanceEvent] = []
    target_weights_records: list[dict] = []
    warnings: list[str] = []
    prev_target_w: np.ndarray | None = None
    current_w: np.ndarray | None = None

    for t in range(n_dates):
        current_date = dates[t]

        if t == 0:
            # --- GIORNO 0: investimento iniziale ---
            new_weights, issues = decide_weights(
                returns, as_of=current_date.date(),
                profile=profile, asset_class_map=asset_class_map,
                horizon_years=horizon_years,
                mean_method=mean_method, cov_method=cov_method,
                window_type=window_type, window_days=window_days,
            )

            if issues:
                for issue in issues:
                    warnings.append(f"{current_date.date()}: {issue}")

            if new_weights is None:
                raise ValueError(
                    f"Ottimizzazione iniziale infeasible a {current_date.date()}"
                )

            target_w = np.array([new_weights.get(tk, 0.0) for tk in tickers])
            w_sum = target_w.sum()
            if w_sum > 0:
                target_w = target_w / w_sum

            current_w = target_w.copy()
            initial_turnover = float(target_w.sum())
            initial_cost = initial_capital * initial_turnover * tx_cost_frac
            pv[0] = initial_capital - initial_cost

            rebalance_log.append(RebalanceEvent(
                date=current_date.date(),
                turnover=initial_turnover,
                cost=float(initial_cost),
                weights_before={tk: 0.0 for tk in tickers},
                weights_after={
                    tk: float(target_w[i]) for i, tk in enumerate(tickers)
                },
            ))

            target_weights_records.append({
                "date": current_date,
                **{tk: float(target_w[i]) for i, tk in enumerate(tickers)},
            })
            prev_target_w = target_w.copy()
            weights_hist[0] = current_w
            continue

        # --- GIORNO t >= 1 ---
        daily_ret = daily_returns.iloc[t].values
        daily_ret = np.nan_to_num(daily_ret, nan=0.0)

        # Evolvi i pesi col mercato
        current_w = _evolve_weights(current_w, daily_ret)

        # Aggiorna il valore del portafoglio
        port_return = np.dot(weights_hist[t - 1], daily_ret)
        pv[t] = pv[t - 1] * (1 + port_return)

        # Check ribilanciamento
        if current_date in rebalance_set:
            new_weights, issues = decide_weights(
                returns, as_of=current_date.date(),
                profile=profile, asset_class_map=asset_class_map,
                horizon_years=horizon_years,
                mean_method=mean_method, cov_method=cov_method,
                window_type=window_type, window_days=window_days,
            )

            if issues:
                for issue in issues:
                    warnings.append(f"{current_date.date()}: {issue}")

            if new_weights is not None:
                target_w = np.array(
                    [new_weights.get(tk, 0.0) for tk in tickers]
                )
                w_sum = target_w.sum()
                if w_sum > 0:
                    target_w = target_w / w_sum

                # Controllo stabilita' dei pesi target
                if prev_target_w is not None:
                    max_change = float(
                        np.max(np.abs(target_w - prev_target_w))
                    )
                    if max_change > MAX_WEIGHT_CHANGE_WARN:
                        warnings.append(
                            f"{current_date.date()}: cambio target massimo "
                            f"{max_change:.2%} (>{MAX_WEIGHT_CHANGE_WARN:.0%}), "
                            f"possibile instabilita' della stima"
                        )

                # Applica ribilanciamento
                turnover = float(np.abs(current_w - target_w).sum())
                cost = pv[t] * turnover * tx_cost_frac
                pv[t] -= cost

                rebalance_log.append(RebalanceEvent(
                    date=current_date.date(),
                    turnover=turnover,
                    cost=float(cost),
                    weights_before={
                        tk: float(current_w[i])
                        for i, tk in enumerate(tickers)
                    },
                    weights_after={
                        tk: float(target_w[i])
                        for i, tk in enumerate(tickers)
                    },
                ))

                target_weights_records.append({
                    "date": current_date,
                    **{
                        tk: float(target_w[i])
                        for i, tk in enumerate(tickers)
                    },
                })

                prev_target_w = target_w.copy()
                current_w = target_w.copy()
            else:
                warnings.append(
                    f"{current_date.date()}: ottimizzazione infeasible, "
                    f"pesi invariati"
                )

        weights_hist[t] = current_w

    # --- Costruisci output ---
    pv_series = pd.Series(pv, index=dates, name="portfolio_value")
    wh_df = pd.DataFrame(weights_hist, index=dates, columns=tickers)
    metrics = compute_metrics(pv_series, rebalance_log)

    tw_df = pd.DataFrame(target_weights_records)
    if len(tw_df) > 0:
        tw_df = tw_df.set_index("date")
    else:
        tw_df = pd.DataFrame(columns=tickers)

    # --- Sanity warnings ---
    if metrics["sharpe"] > SUSPICIOUS_SHARPE:
        warnings.append(
            f"ATTENZIONE: Sharpe {metrics['sharpe']:.2f} sospettosamente "
            f"alto (>{SUSPICIOUS_SHARPE}). Verificare anti-lookahead."
        )

    if metrics["max_drawdown"] > -0.02 and n_dates > 252:
        warnings.append(
            f"ATTENZIONE: max drawdown {metrics['max_drawdown']:.2%} quasi "
            f"nullo su {n_dates} giorni. Possibile lookahead."
        )

    metadata = {
        "strategy": "walk_forward",
        "profile": profile.name,
        "frequency": frequency,
        "window_type": window_type,
        "window_days": window_days,
        "horizon_years": horizon_years,
        "mean_method": mean_method,
        "cov_method": cov_method,
        "initial_capital": initial_capital,
        "tx_cost_bps": tx_cost_bps,
        "n_days": n_dates,
        "n_rebalances_planned": len(rebalance_dates),
        "tickers": tickers,
        "sim_start": str(sim_start),
        "sim_end": str(sim_end),
    }

    logger.info(
        f"Walk-forward completato: {n_dates} giorni, "
        f"{metrics['n_rebalances']} ribilanciamenti, "
        f"CAGR={metrics['cagr']:.2%}, Sharpe={metrics['sharpe']:.2f}, "
        f"MaxDD={metrics['max_drawdown']:.2%}"
    )

    if warnings:
        for w in warnings:
            logger.warning(f"WALKFORWARD: {w}")

    return WalkForwardResult(
        portfolio_value=pv_series,
        weights_history=wh_df,
        target_weights_history=tw_df,
        metrics=metrics,
        rebalance_log=rebalance_log,
        validation_warnings=warnings,
        metadata=metadata,
    )
