"""
Profilazione cliente (Fase 4).

Traduce un profilo investitore + orizzonte temporale in input concreti
per il motore di ottimizzazione (obiettivo + vincoli), e produce il
portafoglio adatto.

OUTPUT (contratto per la Fase 5):
    ProfileResult con:
    - portfolio: PortfolioResult (pesi + statistiche)
    - profile_name: nome del profilo
    - profile_config: configurazione applicata
    - horizon_years: orizzonte temporale
    - effective_vol_ceiling: tetto di vol dopo aggiustamento orizzonte
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml
import numpy as np

from .constraints import PortfolioConstraints
from .optimizer import (
    PortfolioResult,
    get_objective,
    validate_result,
)
from .estimation import (
    ParameterEstimate,
    filter_params,
    get_crypto_tickers,
    CRYPTO_ASSET_CLASS,
)

logger = logging.getLogger(__name__)

DEFAULT_PROFILES_PATH = Path(__file__).parent.parent / "config" / "profiles.yaml"

# Ordine canonico dei profili (dal meno al più rischioso)
PROFILE_ORDER = ["conservativo", "moderato", "bilanciato", "dinamico", "aggressivo"]


@dataclass
class ProfileConfig:
    """Configurazione di un singolo profilo, caricata dal YAML."""
    name: str
    description: str
    vol_ceiling: float | None     # None = nessun tetto
    max_weight: float
    objective: str                # nome dell'obiettivo (es. "max_return", "max_sharpe")
    group_limits: dict[str, tuple[float, float]]


@dataclass
class HorizonAdjustment:
    """Regola di aggiustamento per fascia di orizzonte."""
    label: str
    max_years: int
    vol_factor: float


@dataclass
class ProfileResult:
    """Contratto di output della Fase 4.

    Questo oggetto sarà l'input della Fase 5.
    """
    portfolio: PortfolioResult
    profile_name: str
    profile_config: ProfileConfig
    horizon_years: int
    horizon_band: str                  # "short", "medium", "long"
    effective_vol_ceiling: float | None
    validation_issues: list[str] = field(default_factory=list)


def load_profiles(path: Path | None = None) -> dict[str, ProfileConfig]:
    """Carica tutti i profili dal file YAML."""
    path = path or DEFAULT_PROFILES_PATH
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    profiles = {}
    for name, cfg in data["profiles"].items():
        group_limits = {}
        for group, limits in cfg.get("group_limits", {}).items():
            group_limits[group] = (float(limits[0]), float(limits[1]))

        profiles[name] = ProfileConfig(
            name=name,
            description=cfg.get("description", ""),
            vol_ceiling=cfg.get("vol_ceiling"),  # None se "null" in YAML
            max_weight=float(cfg["max_weight"]),
            objective=cfg["objective"],
            group_limits=group_limits,
        )

    return profiles


def load_horizon_adjustments(path: Path | None = None) -> list[HorizonAdjustment]:
    """Carica le regole di aggiustamento per orizzonte."""
    path = path or DEFAULT_PROFILES_PATH
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    adjustments = []
    for label, cfg in data["horizon_adjustments"].items():
        adjustments.append(HorizonAdjustment(
            label=label,
            max_years=int(cfg["max_years"]),
            vol_factor=float(cfg["vol_factor"]),
        ))

    # Ordina per max_years crescente
    adjustments.sort(key=lambda a: a.max_years)
    return adjustments


def get_horizon_band(
    horizon_years: int,
    adjustments: list[HorizonAdjustment] | None = None,
) -> tuple[str, float]:
    """Determina la fascia di orizzonte e il fattore di aggiustamento.

    Restituisce (label, vol_factor).
    """
    if adjustments is None:
        adjustments = load_horizon_adjustments()

    for adj in adjustments:
        if horizon_years <= adj.max_years:
            return adj.label, adj.vol_factor

    # Fallback: ultimo (più lungo)
    return adjustments[-1].label, adjustments[-1].vol_factor


def profile_to_constraints(
    profile: ProfileConfig,
    horizon_years: int,
    adjustments: list[HorizonAdjustment] | None = None,
) -> tuple[PortfolioConstraints, str, float | None]:
    """Mappa un profilo + orizzonte a vincoli e obiettivo.

    Restituisce:
        - PortfolioConstraints configurato
        - horizon_band (label)
        - effective_vol_ceiling (dopo aggiustamento orizzonte)
    """
    band, vol_factor = get_horizon_band(horizon_years, adjustments)

    # Calcola tetto di volatilità effettivo
    if profile.vol_ceiling is not None:
        effective_vol = profile.vol_ceiling * vol_factor
    else:
        effective_vol = None

    logger.info(
        f"Profilo '{profile.name}', orizzonte {horizon_years}y (fascia: {band}): "
        f"vol_ceiling {profile.vol_ceiling} * {vol_factor} = {effective_vol}"
    )

    # Escludi il vincolo crypto: le cripto non entrano nell'ottimizzatore
    # (gestite separatamente dal satellite in core_satellite)
    core_group_limits = {
        k: v for k, v in profile.group_limits.items()
        if k != CRYPTO_ASSET_CLASS
    }

    constraints = PortfolioConstraints(
        long_only=True,
        fully_invested=True,
        min_weight=0.0,
        max_weight=profile.max_weight,
        group_constraints=core_group_limits,
        risk_ceiling=effective_vol,
    )

    return constraints, band, effective_vol


def build_portfolio_for_profile(
    profile: ProfileConfig,
    params: ParameterEstimate,
    horizon_years: int = 5,
    asset_class_map: dict[str, str] | None = None,
    adjustments: list[HorizonAdjustment] | None = None,
) -> ProfileResult:
    """Costruisce il portafoglio ottimale per un dato profilo e orizzonte.

    Parametri:
        profile: configurazione del profilo
        params: stime mu e Sigma (dalla Fase 2)
        horizon_years: orizzonte dell'investitore in anni
        asset_class_map: ticker -> asset_class (dall'universo)
        adjustments: regole di orizzonte (default: da YAML)
    """
    constraints, band, effective_vol = profile_to_constraints(
        profile, horizon_years, adjustments
    )

    # Filtra le cripto dai parametri: il core si ottimizza solo su tradizionali
    if asset_class_map is not None:
        crypto_set = get_crypto_tickers(params.tickers, asset_class_map)
        if crypto_set:
            params = filter_params(params, crypto_set)
            logger.info(f"Profilo '{profile.name}': escluse cripto dal core: "
                        f"{sorted(crypto_set)}")

    # Seleziona l'obiettivo
    objective = get_objective(profile.objective)

    logger.info(f"Ottimizzazione profilo '{profile.name}': "
                f"obiettivo={profile.objective}, "
                f"vol_ceiling={effective_vol}")

    # Risolvi
    result = objective.solve(params, constraints, asset_class_map)

    # Validazione
    issues = []
    if result.is_feasible():
        issues = validate_result(result, constraints, asset_class_map)

        # Controllo aggiuntivo: volatilità <= tetto effettivo
        if effective_vol is not None:
            port_vol = result.stats["volatility"]
            if port_vol > effective_vol + 1e-3:
                msg = (f"Profilo '{profile.name}': vol {port_vol:.2%} > "
                       f"tetto {effective_vol:.2%}")
                issues.append(msg)
                logger.warning(msg)
    else:
        issues.append(f"Profilo '{profile.name}': ottimizzazione INFEASIBLE")
        logger.error(issues[-1])

    return ProfileResult(
        portfolio=result,
        profile_name=profile.name,
        profile_config=profile,
        horizon_years=horizon_years,
        horizon_band=band,
        effective_vol_ceiling=effective_vol,
        validation_issues=issues,
    )


def build_all_profiles(
    params: ParameterEstimate,
    horizon_years: int = 5,
    asset_class_map: dict[str, str] | None = None,
    profiles_path: Path | None = None,
) -> list[ProfileResult]:
    """Costruisce i portafogli per tutti i profili definiti.

    Restituisce la lista ordinata dal più conservativo al più aggressivo.
    """
    profiles = load_profiles(profiles_path)
    adjustments = load_horizon_adjustments(profiles_path)

    results = []
    for name in PROFILE_ORDER:
        if name not in profiles:
            logger.warning(f"Profilo '{name}' non trovato nella configurazione, saltato")
            continue
        result = build_portfolio_for_profile(
            profiles[name], params, horizon_years, asset_class_map, adjustments
        )
        results.append(result)

    return results


def validate_monotonicity(results: list[ProfileResult]) -> list[str]:
    """Verifica che salendo di profilo la volatilità non diminuisca.

    Restituisce lista di problemi trovati.
    """
    issues = []
    for i in range(1, len(results)):
        prev = results[i - 1]
        curr = results[i]

        if not prev.portfolio.is_feasible() or not curr.portfolio.is_feasible():
            continue

        vol_prev = prev.portfolio.stats["volatility"]
        vol_curr = curr.portfolio.stats["volatility"]

        if vol_curr < vol_prev - 1e-4:
            msg = (f"MONOTONICITA' VIOLATA: '{curr.profile_name}' "
                   f"(vol {vol_curr:.2%}) < '{prev.profile_name}' "
                   f"(vol {vol_prev:.2%})")
            issues.append(msg)
            logger.warning(msg)

    if not issues:
        logger.info("Monotonicita' del rischio tra profili: OK")

    return issues
