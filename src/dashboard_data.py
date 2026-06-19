"""
Logica non-UI per la dashboard (Fase 9).

Funzioni testabili che preparano i dati per la dashboard Streamlit.
La UI (app.py) chiama queste funzioni e mostra i risultati.

Tutte le funzioni delegano al motore esistente (Fasi 1-8):
nessuna logica finanziaria viene duplicata.
"""

import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from .pipeline import run_pipeline, DataBundle
from .estimation import estimate_parameters, ParameterEstimate
from .profiles import (
    load_profiles,
    build_portfolio_for_profile,
    build_all_profiles,
    ProfileResult,
    ProfileConfig,
    PROFILE_ORDER,
)
from .core_satellite import (
    build_core_satellite,
    CoreSatelliteResult,
    DEFAULT_SATELLITE,
)
from .strategies import simulate, StrategyResult, BuyAndHold, PeriodicRebalance, ThresholdRebalance
from .reporting import (
    build_report,
    build_comparison,
    render_pdf,
    StrategyReport,
    ComparisonReport,
    _check_weasyprint,
)
from .costs import (
    build_cost_breakdown,
    build_tax_breakdown,
    CostBreakdown,
    TaxBreakdown,
    DEFAULT_CAPITAL_EUR,
)
from .pac import (
    simulate_pac,
    compare_pac_vs_lumpsum,
    PacResult,
    PacComparison,
)
from .universe import load_universe

logger = logging.getLogger(__name__)

# Periodo dati di default (coerente con gli script di esempio)
DATA_START = date(2015, 1, 2)
DATA_END = date(2024, 12, 31)
SIM_START = date(2020, 1, 2)


# ============================================================
# Caricamento dati
# ============================================================

def load_data(refresh: bool = False) -> DataBundle:
    """Carica i dati dalla cache (default) o da Yahoo Finance.

    Di default usa la cache locale (parquet in cache/). La dashboard
    funziona offline e senza dipendere da Yahoo Finance.
    Se refresh=True, ri-scarica da Yahoo Finance e aggiorna la cache.
    """
    return run_pipeline(
        start=DATA_START,
        end=DATA_END,
        use_cache=True,
        refresh_cache=refresh,
    )


def estimate_params(returns: pd.DataFrame) -> ParameterEstimate:
    """Stima parametri mu/Sigma con Bayes-Stein / Ledoit-Wolf."""
    return estimate_parameters(
        returns,
        mean_method="bayes_stein",
        cov_method="ledoit_wolf",
    )


# ============================================================
# Costruzione portafoglio
# ============================================================

@dataclass
class DashboardResult:
    """Risultato completo per la dashboard: portafoglio + backtest + costi + report."""
    profile_result: ProfileResult
    core_satellite: CoreSatelliteResult | None
    strategy_result: StrategyResult | None
    report: StrategyReport
    cost_breakdown: CostBreakdown | None
    tax_breakdown: TaxBreakdown | None


def build_portfolio(
    params: ParameterEstimate,
    profile_name: str,
    horizon_years: int,
    crypto_weight: float,
    satellite_mode: str,
    strategy_name: str,
    strategy_freq: str,
    capital_eur: float,
    prices: pd.DataFrame,
) -> DashboardResult:
    """Costruisce il portafoglio completo con backtest, costi e report.

    Parametri:
        params: stime mu/Sigma
        profile_name: nome del profilo (es. "bilanciato")
        horizon_years: orizzonte temporale in anni
        crypto_weight: quota satellite cripto (0.0 - tetto profilo)
        satellite_mode: "btc" (unica opzione; ETH rimosso dall'universo)
        strategy_name: "buy_and_hold", "periodic", "threshold"
        strategy_freq: frequenza ribilanciamento ("monthly", "quarterly", "annual")
        capital_eur: capitale di riferimento in EUR per costi/tasse
        prices: prezzi puliti (per il backtest)
    """
    profiles = load_profiles()
    profile = profiles[profile_name]
    ac_map = load_universe()["asset_class"].to_dict()

    # Core-satellite (se crypto > 0)
    cs = None
    if crypto_weight > 0:
        cs = build_core_satellite(
            profile, params, ac_map,
            crypto_weight=crypto_weight,
            horizon_years=horizon_years,
        )
        pr = cs.profile_result
    else:
        pr = build_portfolio_for_profile(
            profile, params, horizon_years=horizon_years, asset_class_map=ac_map,
        )

    # Strategia
    if strategy_name == "buy_and_hold":
        strategy = BuyAndHold()
    elif strategy_name == "threshold":
        strategy = ThresholdRebalance()
    else:
        strategy = PeriodicRebalance(frequency=strategy_freq)

    # Backtest
    weights = cs.combined_weights if cs else pr.portfolio.weights
    prices_sim = prices.loc[str(SIM_START):str(DATA_END)]
    bt = None
    if len(prices_sim) > 10:
        try:
            bt = simulate(prices_sim, weights, strategy, tx_cost_bps=0)
        except Exception as e:
            logger.warning(f"Backtest fallito: {e}")

    # Report
    freq_label = strategy_freq if strategy_name == "periodic" else strategy_name
    report = build_report(
        pr,
        backtest_result=bt,
        core_satellite_result=cs,
        rebalance_frequency=freq_label,
    )

    # Costi e tasse
    cb = None
    tb = None
    if bt is not None:
        cb = build_cost_breakdown(
            bt.portfolio_value, bt.weights_history, bt.rebalance_log,
            weights, ac_map, capital_eur=capital_eur,
        )
        tb = build_tax_breakdown(
            bt.portfolio_value, bt.rebalance_log, ac_map,
            cost_breakdown=cb, capital_eur=capital_eur,
        )

    return DashboardResult(
        profile_result=pr,
        core_satellite=cs,
        strategy_result=bt,
        report=report,
        cost_breakdown=cb,
        tax_breakdown=tb,
    )


# ============================================================
# Confronto profili
# ============================================================

@dataclass
class ProfileComparison:
    """Dati per la tabella/grafico di confronto profili."""
    names: list[str]
    volatilities: list[float]
    returns: list[float]
    sharpes: list[float]
    max_drawdowns: list[float | None]
    class_allocations: list[dict[str, float]]


def build_profile_comparison(
    params: ParameterEstimate,
    horizon_years: int,
    prices: pd.DataFrame,
) -> ProfileComparison:
    """Costruisce il confronto tra tutti e 5 i profili."""
    ac_map = load_universe()["asset_class"].to_dict()
    results = build_all_profiles(params, horizon_years=horizon_years, asset_class_map=ac_map)

    prices_sim = prices.loc[str(SIM_START):str(DATA_END)]
    strategy = PeriodicRebalance(frequency="quarterly")

    names, vols, rets, sharpes, mdds, class_allocs = [], [], [], [], [], []

    for pr in results:
        stats = pr.portfolio.stats
        names.append(pr.profile_name)
        vols.append(stats["volatility"])
        rets.append(stats["expected_return"])
        sharpes.append(stats["sharpe_ratio"])

        mdd = None
        if pr.portfolio.is_feasible() and len(prices_sim) > 10:
            try:
                bt = simulate(prices_sim, pr.portfolio.weights, strategy, tx_cost_bps=0)
                mdd = bt.metrics["max_drawdown"]
            except Exception:
                pass
        mdds.append(mdd)

        # Allocazione per classe
        ca: dict[str, float] = {}
        for ticker, w in pr.portfolio.weights.items():
            if abs(w) > 1e-6:
                ac = ac_map.get(ticker, "altro")
                ca[ac] = ca.get(ac, 0.0) + w
        class_allocs.append(ca)

    return ProfileComparison(
        names=names, volatilities=vols, returns=rets,
        sharpes=sharpes, max_drawdowns=mdds, class_allocations=class_allocs,
    )


# ============================================================
# PDF
# ============================================================

def can_render_pdf() -> bool:
    """Verifica se weasyprint e' disponibile."""
    return _check_weasyprint()


def generate_pdf_bytes(report: StrategyReport) -> bytes | None:
    """Genera il PDF e restituisce i bytes, o None se weasyprint non disponibile."""
    try:
        from .reporting import _render_profile_html
        import weasyprint
        html = _render_profile_html(report)
        return weasyprint.HTML(string=html).write_pdf()
    except (ImportError, OSError) as e:
        logger.warning(f"PDF non generabile: {e}")
        return None


# ============================================================
# PAC (Piano di Accumulo del Capitale)
# ============================================================

def build_pac_comparison(
    params: ParameterEstimate,
    profile_name: str,
    horizon_years: int,
    crypto_weight: float,
    satellite_mode: str,
    strategy_name: str,
    strategy_freq: str,
    prices: pd.DataFrame,
    contribution: float,
    pac_frequency: str,
) -> PacComparison:
    """Costruisce il confronto PAC vs somma unica.

    Parametri:
        contribution: importo di ogni versamento PAC (EUR)
        pac_frequency: "monthly", "quarterly", "annual"
        (altri parametri: stessi di build_portfolio)
    """
    profiles = load_profiles()
    profile = profiles[profile_name]
    ac_map = load_universe()["asset_class"].to_dict()

    # Calcola i pesi target (stessa logica di build_portfolio)
    cs = None
    if crypto_weight > 0:
        cs = build_core_satellite(
            profile, params, ac_map,
            crypto_weight=crypto_weight,
            horizon_years=horizon_years,
        )
        pr = cs.profile_result
    else:
        pr = build_portfolio_for_profile(
            profile, params, horizon_years=horizon_years, asset_class_map=ac_map,
        )

    weights = cs.combined_weights if cs else pr.portfolio.weights

    # Strategia
    if strategy_name == "buy_and_hold":
        strategy = BuyAndHold()
    elif strategy_name == "threshold":
        strategy = ThresholdRebalance()
    else:
        strategy = PeriodicRebalance(frequency=strategy_freq)

    prices_sim = prices.loc[str(SIM_START):str(DATA_END)]

    return compare_pac_vs_lumpsum(
        prices_sim, weights, strategy,
        contribution=contribution,
        frequency=pac_frequency,
        asset_class_map=ac_map,
    )
