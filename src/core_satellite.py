"""
Costruzione core-satellite del portafoglio.

Le classi satellite (crypto, stock) NON entrano nell'ottimizzatore.
Diventano "sleeve" satellite decisi esplicitamente dall'utente,
aggiunti sopra un "core" costruito sui soli asset tradizionali.

Costruzione:
1. CORE: ottimizzatore su asset tradizionali (no crypto, no stock),
   con i vincoli del profilo (vol ceiling, tetti di classe, max per asset).
2. SATELLITE: quote satellite esplicite, ognuna legata a una classe.
   Ogni quota deve rispettare il tetto del profilo per quella classe.
3. COMBINAZIONE: pesi_finali = core * (1 - somma_satellite) + satellite.

NOTA SUL RISCHIO:
    Il core rispetta il tetto di volatilita' del profilo. I satellite
    si aggiungono SOPRA: la volatilita' COMBINATA puo' superare il tetto
    nominale. E' voluto: i satellite sono rischi extra scelti consapevolmente,
    limitati dal tetto del profilo. Le statistiche combinate (rendimento,
    volatilita') sono sempre calcolate e riportate, cosi' l'effetto e'
    trasparente.
"""

import logging
from dataclasses import dataclass, field

import numpy as np

from .estimation import (
    ParameterEstimate,
    filter_params,
    get_satellite_tickers,
    CRYPTO_ASSET_CLASS,
    STOCK_ASSET_CLASS,
    SATELLITE_ASSET_CLASSES,
)
from .profiles import (
    ProfileConfig,
    ProfileResult,
    build_portfolio_for_profile,
)
from .config import get_risk_free_rate
from .optimizer import _historical_cvar, _parametric_cvar, MIN_SCENARIOS_CVAR

logger = logging.getLogger(__name__)

# Configurazione satellite predefinita (solo BTC; ETH rimosso dall'universo)
DEFAULT_SATELLITE: dict[str, float] = {"BTC-EUR": 1.0}

# Alias per backward compat
_filter_params = filter_params


@dataclass
class SatelliteSleeve:
    """Singolo sleeve satellite (crypto, stock, ...)."""
    asset_class: str
    weight_requested: float
    weight_actual: float
    tickers: dict[str, float]  # ticker -> peso assoluto nel combinato


@dataclass
class CoreSatelliteResult:
    """Risultato della costruzione core-satellite.

    Compatibile con le Fasi 5-6: usare combined_weights come target_weights
    in simulate() o run_walkforward().
    """
    core_weights: dict[str, float]          # Pesi core (somma=1, no satellite)
    satellite_weights: dict[str, float]     # Pesi satellite TUTTI {ticker: peso}
    combined_weights: dict[str, float]      # Pesi finali (somma=1)
    crypto_weight_requested: float          # Quota cripto richiesta (backward compat)
    crypto_weight_actual: float             # Quota effettiva (dopo clamp)
    core_stats: dict[str, float]            # Stats del solo core
    combined_stats: dict[str, float]        # Stats del portafoglio combinato
    profile_result: ProfileResult           # ProfileResult del core
    validation_issues: list[str] = field(default_factory=list)
    sleeves: list[SatelliteSleeve] = field(default_factory=list)
    stock_weight_requested: float = 0.0
    stock_weight_actual: float = 0.0


def _compute_combined_stats(
    weights: dict[str, float],
    params: ParameterEstimate,
) -> dict[str, float]:
    """Calcola le statistiche del portafoglio combinato usando i parametri completi."""
    w = np.array([weights.get(t, 0.0) for t in params.tickers])
    port_ret = float(params.mu @ w)
    port_var = float(w @ params.cov @ w)
    port_vol = float(np.sqrt(max(port_var, 0)))
    rf = get_risk_free_rate()
    sharpe = (
        (port_ret - rf) / port_vol
        if port_vol > 1e-10 else 0.0
    )

    # CVaR: storico (default) con fallback parametrico
    ann_factor = params.metadata.get("ann_factor", 252)
    cvar_parametric = _parametric_cvar(port_ret, port_vol)

    if params.returns is not None and len(params.returns) >= MIN_SCENARIOS_CVAR:
        port_daily_rets = params.returns @ w
        cvar_95 = _historical_cvar(port_daily_rets, ann_factor=ann_factor)
    else:
        cvar_95 = cvar_parametric

    return {
        "expected_return": port_ret,
        "volatility": port_vol,
        "sharpe_ratio": sharpe,
        "cvar_95": cvar_95,
        "cvar_95_parametric": cvar_parametric,
        "risk_free_rate": rf,
    }


def _validate_sleeve_tickers(
    tickers_rel: dict[str, float],
    expected_class: str,
    all_tickers: set[str],
    asset_class_map: dict[str, str],
) -> tuple[dict[str, float], list[str]]:
    """Valida i ticker di uno sleeve satellite.

    Restituisce (ticker_validi, issues).
    """
    valid: dict[str, float] = {}
    issues: list[str] = []
    for t, rel_w in tickers_rel.items():
        if t not in all_tickers:
            msg = f"Satellite ticker '{t}' non presente nei parametri, escluso"
            logger.warning(msg)
            issues.append(msg)
        elif asset_class_map.get(t) != expected_class:
            actual = asset_class_map.get(t, "?")
            msg = (f"Satellite ticker '{t}' e' classe '{actual}', "
                   f"atteso '{expected_class}', escluso")
            logger.warning(msg)
            issues.append(msg)
        else:
            valid[t] = rel_w
    return valid, issues


def _clamp_weight(
    weight: float,
    max_weight: float,
    class_name: str,
) -> tuple[float, list[str]]:
    """Limita il peso al tetto del profilo. Restituisce (peso_clampato, issues)."""
    issues: list[str] = []
    if weight > max_weight + 1e-10:
        msg = (f"{class_name}_weight {weight:.2%} > tetto profilo "
               f"{max_weight:.2%}, limitato a {max_weight:.2%}")
        logger.warning(msg)
        issues.append(msg)
        weight = max_weight
    if weight < 0:
        weight = 0.0
    return weight, issues


def build_core_satellite(
    profile: ProfileConfig,
    params: ParameterEstimate,
    asset_class_map: dict[str, str],
    crypto_weight: float = 0.0,
    satellite_tickers: dict[str, float] | None = None,
    horizon_years: int = 5,
    stock_weight: float = 0.0,
    stock_tickers: dict[str, float] | None = None,
) -> CoreSatelliteResult:
    """Costruisce un portafoglio core-satellite.

    Parametri:
        profile: configurazione del profilo investitore
        params: stime mu/Sigma COMPLETE (con crypto e stock)
        asset_class_map: ticker -> asset class
        crypto_weight: quota satellite cripto desiderata (0.0 - 1.0)
        satellite_tickers: composizione satellite crypto
            {ticker: peso_relativo}. Default: {"BTC-EUR": 1.0}.
        horizon_years: orizzonte investitore
        stock_weight: quota satellite azioni singole desiderata (0.0 - 1.0)
        stock_tickers: composizione satellite stock
            {ticker: peso_relativo}. Es. {"AAPL": 0.5, "MSFT": 0.5}.

    Restituisce:
        CoreSatelliteResult con core, satellite, pesi combinati e stats.
    """
    if satellite_tickers is None:
        satellite_tickers = dict(DEFAULT_SATELLITE)

    issues: list[str] = []
    crypto_requested = crypto_weight
    stock_requested = stock_weight
    all_tickers_set = set(params.tickers)
    sleeves: list[SatelliteSleeve] = []

    # --- 1. Clamp crypto al tetto del profilo ---
    max_crypto = profile.group_limits.get(CRYPTO_ASSET_CLASS, (0.0, 0.0))[1]
    crypto_weight, clamp_issues = _clamp_weight(crypto_weight, max_crypto, "crypto")
    issues.extend(clamp_issues)

    # --- 2. Valida satellite crypto tickers ---
    valid_crypto, val_issues = _validate_sleeve_tickers(
        satellite_tickers, CRYPTO_ASSET_CLASS, all_tickers_set, asset_class_map,
    )
    issues.extend(val_issues)

    if crypto_weight > 0 and not valid_crypto:
        msg = "Nessun satellite crypto ticker valido, crypto_weight forzato a 0"
        logger.warning(msg)
        issues.append(msg)
        crypto_weight = 0.0

    # --- 3. Clamp stock al tetto del profilo ---
    max_stock = profile.group_limits.get(STOCK_ASSET_CLASS, (0.0, 0.0))[1]
    stock_weight, clamp_issues = _clamp_weight(stock_weight, max_stock, "stock")
    issues.extend(clamp_issues)

    # --- 4. Valida satellite stock tickers ---
    valid_stock: dict[str, float] = {}
    if stock_tickers and stock_weight > 0:
        valid_stock, val_issues = _validate_sleeve_tickers(
            stock_tickers, STOCK_ASSET_CLASS, all_tickers_set, asset_class_map,
        )
        issues.extend(val_issues)

        if not valid_stock:
            msg = "Nessun satellite stock ticker valido, stock_weight forzato a 0"
            logger.warning(msg)
            issues.append(msg)
            stock_weight = 0.0

    # --- 5. Filtra parametri (escludi TUTTE le classi satellite) ---
    sat_set = get_satellite_tickers(params.tickers, asset_class_map)
    if sat_set:
        core_params = filter_params(params, sat_set)
    else:
        core_params = params

    # --- 6. Profilo core (senza vincoli satellite) ---
    core_group_limits = {
        k: v for k, v in profile.group_limits.items()
        if k not in SATELLITE_ASSET_CLASSES
    }
    core_profile = ProfileConfig(
        name=profile.name,
        description=profile.description,
        vol_ceiling=profile.vol_ceiling,
        max_weight=profile.max_weight,
        objective=profile.objective,
        group_limits=core_group_limits,
    )

    # --- 7. Ottimizza il core ---
    core_result = build_portfolio_for_profile(
        core_profile, core_params,
        horizon_years=horizon_years,
        asset_class_map=asset_class_map,
    )

    if not core_result.portfolio.is_feasible():
        issues.append("Core infeasible")
        return CoreSatelliteResult(
            core_weights={},
            satellite_weights={},
            combined_weights={},
            crypto_weight_requested=crypto_requested,
            crypto_weight_actual=0.0,
            core_stats=core_result.portfolio.stats,
            combined_stats=core_result.portfolio.stats,
            profile_result=core_result,
            validation_issues=issues,
            stock_weight_requested=stock_requested,
            stock_weight_actual=0.0,
        )

    core_weights = core_result.portfolio.weights
    core_stats = core_result.portfolio.stats

    # --- 8. Verifica: il core non contiene classi satellite ---
    for t in core_weights:
        if asset_class_map.get(t) in SATELLITE_ASSET_CLASSES:
            msg = f"ERRORE: satellite ticker '{t}' nel core"
            issues.append(msg)
            logger.error(msg)

    # --- 9. Costruisci i pesi combinati ---
    total_satellite = crypto_weight + stock_weight
    combined: dict[str, float] = {}
    satellite_out: dict[str, float] = {}

    # Core scalato
    for t, w in core_weights.items():
        combined[t] = w * (1.0 - total_satellite)

    # Satellite crypto
    if crypto_weight > 0 and valid_crypto:
        sat_total = sum(valid_crypto.values())
        crypto_sleeve_tickers: dict[str, float] = {}
        for t, rel_w in valid_crypto.items():
            sat_w = crypto_weight * rel_w / sat_total
            satellite_out[t] = sat_w
            crypto_sleeve_tickers[t] = sat_w
            combined[t] = combined.get(t, 0.0) + sat_w
        sleeves.append(SatelliteSleeve(
            asset_class=CRYPTO_ASSET_CLASS,
            weight_requested=crypto_requested,
            weight_actual=crypto_weight,
            tickers=crypto_sleeve_tickers,
        ))

    # Satellite stock
    if stock_weight > 0 and valid_stock:
        sat_total = sum(valid_stock.values())
        stock_sleeve_tickers: dict[str, float] = {}
        for t, rel_w in valid_stock.items():
            sat_w = stock_weight * rel_w / sat_total
            satellite_out[t] = sat_w
            stock_sleeve_tickers[t] = sat_w
            combined[t] = combined.get(t, 0.0) + sat_w
        sleeves.append(SatelliteSleeve(
            asset_class=STOCK_ASSET_CLASS,
            weight_requested=stock_requested,
            weight_actual=stock_weight,
            tickers=stock_sleeve_tickers,
        ))

    # --- 10. Statistiche combinate (su parametri COMPLETI) ---
    combined_stats = _compute_combined_stats(combined, params)

    logger.info(
        f"Core-satellite '{profile.name}': "
        f"crypto={crypto_weight:.2%} (richiesto={crypto_requested:.2%}), "
        f"stock={stock_weight:.2%} (richiesto={stock_requested:.2%}), "
        f"core_vol={core_stats['volatility']:.2%}, "
        f"combined_vol={combined_stats['volatility']:.2%}"
    )

    # --- 11. Validazione finale ---
    w_sum = sum(combined.values())
    if abs(w_sum - 1.0) > 1e-4:
        issues.append(f"Pesi combinati non sommano a 1: {w_sum:.6f}")

    if any(w < -1e-6 for w in combined.values()):
        neg = {t: w for t, w in combined.items() if w < -1e-6}
        issues.append(f"Pesi negativi: {neg}")

    return CoreSatelliteResult(
        core_weights=core_weights,
        satellite_weights=satellite_out,
        combined_weights=combined,
        crypto_weight_requested=crypto_requested,
        crypto_weight_actual=crypto_weight,
        core_stats=core_stats,
        combined_stats=combined_stats,
        profile_result=core_result,
        validation_issues=issues,
        sleeves=sleeves,
        stock_weight_requested=stock_requested,
        stock_weight_actual=stock_weight,
    )
