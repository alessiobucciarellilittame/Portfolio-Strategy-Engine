"""
Frontiera efficiente: calcola la curva rischio/rendimento.

Genera una serie di portafogli ottimali al variare del rendimento target.
"""

import logging
from dataclasses import dataclass

import numpy as np

from .estimation import ParameterEstimate
from .constraints import PortfolioConstraints
from .optimizer import MinVariance, MinRiskTargetReturn, PortfolioResult

logger = logging.getLogger(__name__)


@dataclass
class EfficientFrontier:
    """Risultato del calcolo della frontiera efficiente."""
    returns: np.ndarray       # Rendimenti attesi dei portafogli sulla frontiera
    volatilities: np.ndarray  # Volatilità corrispondenti
    portfolios: list[PortfolioResult]  # Portafogli ottimali
    n_points: int


def compute_frontier(
    params: ParameterEstimate,
    constraints: PortfolioConstraints,
    asset_class_map: dict[str, str] | None = None,
    n_points: int = 30,
) -> EfficientFrontier:
    """Calcola la frontiera efficiente.

    Procedura:
    1. Trova il portafoglio a minima varianza (estremo sinistro)
    2. Trova il rendimento massimo raggiungibile (estremo destro)
    3. Interpola n_points rendimenti target tra i due estremi
    4. Per ogni target, risolvi min-rischio a rendimento dato

    Parametri:
        params: stime mu e Sigma
        constraints: vincoli base (il target_return viene sovrascritto internamente)
        n_points: numero di punti sulla frontiera
    """
    logger.info(f"Calcolo frontiera efficiente: {n_points} punti")

    # 1. Minima varianza (estremo sinistro)
    min_var_result = MinVariance().solve(params, constraints, asset_class_map)
    if not min_var_result.is_feasible():
        logger.error("Frontiera: minima varianza infeasible")
        return EfficientFrontier(
            returns=np.array([]),
            volatilities=np.array([]),
            portfolios=[],
            n_points=0,
        )

    mu_min = min_var_result.stats["expected_return"]
    vol_min = min_var_result.stats["volatility"]

    # 2. Rendimento massimo raggiungibile
    # Con vincoli (long-only, max_weight), il max rendimento è limitato
    from .optimizer import MaxReturn
    max_ret_result = MaxReturn().solve(params, constraints, asset_class_map)
    if not max_ret_result.is_feasible():
        mu_max = mu_min * 1.5  # fallback
    else:
        mu_max = max_ret_result.stats["expected_return"]

    if mu_max <= mu_min:
        mu_max = mu_min * 1.1 + 0.01

    # 3. Genera target di rendimento
    targets = np.linspace(mu_min, mu_max, n_points)

    # 4. Risolvi per ogni target
    portfolios = []
    returns_list = []
    vols_list = []

    for target in targets:
        c = PortfolioConstraints(
            long_only=constraints.long_only,
            fully_invested=constraints.fully_invested,
            min_weight=constraints.min_weight,
            max_weight=constraints.max_weight,
            group_constraints=constraints.group_constraints,
            return_floor=constraints.return_floor,
            target_return=float(target),
        )
        result = MinRiskTargetReturn().solve(params, c, asset_class_map)

        if result.is_feasible():
            portfolios.append(result)
            returns_list.append(result.stats["expected_return"])
            vols_list.append(result.stats["volatility"])

    logger.info(f"Frontiera: {len(portfolios)}/{n_points} punti risolti")

    return EfficientFrontier(
        returns=np.array(returns_list),
        volatilities=np.array(vols_list),
        portfolios=portfolios,
        n_points=len(portfolios),
    )
