"""
Costruzione core-satellite del portafoglio.

Le cripto NON entrano nell'ottimizzatore (rendimenti estremi distorcerebbero
la stima). Diventano un "satellite" deciso esplicitamente dall'utente,
aggiunto sopra un "core" costruito sui soli asset tradizionali.

Costruzione:
1. CORE: ottimizzatore su asset tradizionali (no crypto), con i vincoli
   del profilo (vol ceiling, tetti di classe, max per asset).
2. SATELLITE: quota cripto esplicita, default = solo BTC.
   Deve rispettare il tetto cripto del profilo.
3. COMBINAZIONE: pesi_finali = core * (1 - crypto_weight) + satellite.

NOTA SUL RISCHIO:
    Il core rispetta il tetto di volatilita' del profilo. Il satellite cripto
    si aggiunge SOPRA: la volatilita' COMBINATA puo' superare il tetto
    nominale. E' voluto: la cripto e' un rischio extra scelto consapevolmente,
    limitato dal tetto del profilo. Le statistiche combinate (rendimento,
    volatilita') sono sempre calcolate e riportate, cosi' l'effetto della
    cripto e' trasparente.
"""

import logging
from dataclasses import dataclass, field

import numpy as np

from .estimation import ParameterEstimate, filter_params, get_crypto_tickers, CRYPTO_ASSET_CLASS
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


@dataclass
class CoreSatelliteResult:
    """Risultato della costruzione core-satellite.

    Compatibile con le Fasi 5-6: usare combined_weights come target_weights
    in simulate() o run_walkforward().
    """
    core_weights: dict[str, float]          # Pesi core (somma=1, no crypto)
    satellite_weights: dict[str, float]     # Pesi satellite {ticker: peso}
    combined_weights: dict[str, float]      # Pesi finali (somma=1)
    crypto_weight_requested: float          # Quota cripto richiesta
    crypto_weight_actual: float             # Quota effettiva (dopo clamp)
    core_stats: dict[str, float]            # Stats del solo core
    combined_stats: dict[str, float]        # Stats del portafoglio combinato
    profile_result: ProfileResult           # ProfileResult del core
    validation_issues: list[str] = field(default_factory=list)


_filter_params = filter_params  # backward compat alias


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


def build_core_satellite(
    profile: ProfileConfig,
    params: ParameterEstimate,
    asset_class_map: dict[str, str],
    crypto_weight: float = 0.0,
    satellite_tickers: dict[str, float] | None = None,
    horizon_years: int = 5,
) -> CoreSatelliteResult:
    """Costruisce un portafoglio core-satellite.

    Parametri:
        profile: configurazione del profilo investitore
        params: stime mu/Sigma COMPLETE (con crypto)
        asset_class_map: ticker -> asset class
        crypto_weight: quota satellite cripto desiderata (0.0 - 1.0)
        satellite_tickers: composizione del satellite
            {ticker: peso_relativo}. Default: {"BTC-EUR": 1.0}.
        horizon_years: orizzonte investitore

    Restituisce:
        CoreSatelliteResult con core, satellite, pesi combinati e stats.
    """
    if satellite_tickers is None:
        satellite_tickers = dict(DEFAULT_SATELLITE)

    issues: list[str] = []
    requested = crypto_weight

    # --- 1. Identifica i ticker crypto ---
    crypto_set = get_crypto_tickers(params.tickers, asset_class_map)
    logger.info(f"Core-satellite: crypto tickers = {sorted(crypto_set)}")

    # --- 2. Clamp crypto_weight al tetto del profilo ---
    max_crypto = profile.group_limits.get(CRYPTO_ASSET_CLASS, (0.0, 0.0))[1]
    if crypto_weight > max_crypto + 1e-10:
        msg = (
            f"crypto_weight {crypto_weight:.2%} > tetto profilo "
            f"{max_crypto:.2%}, limitato a {max_crypto:.2%}"
        )
        logger.warning(msg)
        issues.append(msg)
        crypto_weight = max_crypto

    if crypto_weight < 0:
        crypto_weight = 0.0

    # --- 3. Valida satellite tickers ---
    valid_sat: dict[str, float] = {}
    for t, rel_w in satellite_tickers.items():
        if t not in set(params.tickers):
            msg = f"Satellite ticker '{t}' non presente nei parametri, escluso"
            logger.warning(msg)
            issues.append(msg)
        elif asset_class_map.get(t) != CRYPTO_ASSET_CLASS:
            msg = f"Satellite ticker '{t}' non e' crypto, escluso"
            logger.warning(msg)
            issues.append(msg)
        else:
            valid_sat[t] = rel_w

    if crypto_weight > 0 and not valid_sat:
        msg = "Nessun satellite ticker valido, crypto_weight forzato a 0"
        logger.warning(msg)
        issues.append(msg)
        crypto_weight = 0.0

    # --- 4. Filtra parametri (escludi crypto) ---
    core_params = _filter_params(params, crypto_set)

    # --- 5. Profilo core (senza vincolo crypto) ---
    core_group_limits = {
        k: v for k, v in profile.group_limits.items()
        if k != CRYPTO_ASSET_CLASS
    }
    core_profile = ProfileConfig(
        name=profile.name,
        description=profile.description,
        vol_ceiling=profile.vol_ceiling,
        max_weight=profile.max_weight,
        objective=profile.objective,
        group_limits=core_group_limits,
    )

    # --- 6. Ottimizza il core ---
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
            crypto_weight_requested=requested,
            crypto_weight_actual=0.0,
            core_stats=core_result.portfolio.stats,
            combined_stats=core_result.portfolio.stats,
            profile_result=core_result,
            validation_issues=issues,
        )

    core_weights = core_result.portfolio.weights
    core_stats = core_result.portfolio.stats

    # --- 7. Verifica: il core non contiene crypto ---
    for t in core_weights:
        if asset_class_map.get(t) == CRYPTO_ASSET_CLASS:
            msg = f"ERRORE: crypto ticker '{t}' nel core"
            issues.append(msg)
            logger.error(msg)

    # --- 8. Costruisci i pesi combinati ---
    combined: dict[str, float] = {}

    # Core scalato
    for t, w in core_weights.items():
        combined[t] = w * (1.0 - crypto_weight)

    # Satellite
    satellite_out: dict[str, float] = {}
    if crypto_weight > 0 and valid_sat:
        sat_total = sum(valid_sat.values())
        for t, rel_w in valid_sat.items():
            sat_w = crypto_weight * rel_w / sat_total
            satellite_out[t] = sat_w
            combined[t] = combined.get(t, 0.0) + sat_w

    # --- 9. Statistiche combinate (su parametri COMPLETI) ---
    combined_stats = _compute_combined_stats(combined, params)

    logger.info(
        f"Core-satellite '{profile.name}': "
        f"crypto={crypto_weight:.2%} "
        f"(richiesto={requested:.2%}, max={max_crypto:.2%}), "
        f"core_vol={core_stats['volatility']:.2%}, "
        f"combined_vol={combined_stats['volatility']:.2%}"
    )

    # --- 10. Validazione finale ---
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
        crypto_weight_requested=requested,
        crypto_weight_actual=crypto_weight,
        core_stats=core_stats,
        combined_stats=combined_stats,
        profile_result=core_result,
        validation_issues=issues,
    )
