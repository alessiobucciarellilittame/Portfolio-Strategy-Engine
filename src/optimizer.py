"""
Motore di ottimizzazione di portafoglio (Fase 3).

Incapsula CVXPY dietro un'interfaccia pulita.
Supporta più funzioni obiettivo (selezionabili per nome)
e vincoli configurabili.

OUTPUT (contratto per le fasi successive):
    PortfolioResult con:
    - weights: dict ticker -> peso
    - stats: dict con rendimento atteso, volatilità, sharpe, cvar, ecc.
    - metadata: obiettivo, vincoli, stato solver
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import numpy as np
import cvxpy as cp

from .estimation import ParameterEstimate
from .constraints import PortfolioConstraints
from .config import get_risk_free_rate

logger = logging.getLogger(__name__)

# Soglia minima di scenari per il CVaR storico
MIN_SCENARIOS_CVAR = 20


@dataclass
class PortfolioResult:
    """Contratto di output del motore di ottimizzazione.

    Questo oggetto sarà l'input delle fasi successive.

    Attributi:
        weights: dizionario ticker -> peso
        stats: statistiche del portafoglio
        metadata: informazioni sull'ottimizzazione
    """
    weights: dict[str, float]
    stats: dict[str, float]
    metadata: dict = field(default_factory=dict)

    @property
    def weight_array(self) -> np.ndarray:
        return np.array(list(self.weights.values()))

    @property
    def tickers(self) -> list[str]:
        return list(self.weights.keys())

    def is_feasible(self) -> bool:
        return self.metadata.get("status") == "optimal"


def _historical_cvar(
    portfolio_daily_returns: np.ndarray,
    alpha: float = 0.05,
    ann_factor: int = 252,
) -> float:
    """Calcola il CVaR storico annualizzato dalla distribuzione empirica.

    Procedura:
    1. Ordina i rendimenti giornalieri del portafoglio
    2. Prendi il peggior alpha% (coda sinistra)
    3. CVaR giornaliero = -media(coda)
    4. Annualizza con sqrt(ann_factor)

    Restituisce:
        CVaR annualizzato (positivo = perdita attesa).
    """
    n = len(portfolio_daily_returns)
    cutoff = max(1, int(np.floor(n * alpha)))
    sorted_rets = np.sort(portfolio_daily_returns)
    tail = sorted_rets[:cutoff]
    daily_cvar = -float(np.mean(tail))
    return daily_cvar * np.sqrt(ann_factor)


def _parametric_cvar(
    port_return: float,
    port_vol: float,
    alpha: float = 0.05,
) -> float:
    """Calcola il CVaR parametrico (gaussiano) annualizzato.

    Formula: CVaR_alpha = -(mu - sigma * phi(z_alpha) / alpha)
    """
    from scipy.stats import norm
    z = norm.ppf(alpha)
    pdf_z = norm.pdf(z)
    return -(port_return - port_vol * pdf_z / alpha)


class Objective(ABC):
    """Interfaccia astratta per le funzioni obiettivo."""

    @abstractmethod
    def solve(
        self,
        params: ParameterEstimate,
        constraints: PortfolioConstraints,
        asset_class_map: dict[str, str] | None = None,
    ) -> PortfolioResult:
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        ...


def _build_cvxpy_constraints(
    w: cp.Variable,
    params: ParameterEstimate,
    constraints: PortfolioConstraints,
    asset_class_map: dict[str, str] | None = None,
) -> list:
    """Traduce PortfolioConstraints in vincoli CVXPY."""
    cvx_constraints = []
    p = params.n_assets

    # Somma pesi
    if constraints.fully_invested:
        cvx_constraints.append(cp.sum(w) == 1)
    else:
        cvx_constraints.append(cp.sum(w) <= 1)
        cvx_constraints.append(cp.sum(w) >= 0)

    # Long-only
    if constraints.long_only:
        cvx_constraints.append(w >= 0)

    # Peso min/max per singolo asset
    if constraints.min_weight is not None:
        cvx_constraints.append(w >= constraints.min_weight)
    if constraints.max_weight is not None:
        cvx_constraints.append(w <= constraints.max_weight)

    # Vincoli per gruppo/asset class
    if constraints.group_constraints and asset_class_map:
        for group, (gmin, gmax) in constraints.group_constraints.items():
            indices = [
                i for i, t in enumerate(params.tickers)
                if asset_class_map.get(t) == group
            ]
            if indices:
                group_sum = cp.sum(w[indices])
                cvx_constraints.append(group_sum >= gmin)
                cvx_constraints.append(group_sum <= gmax)

    # Return floor
    if constraints.return_floor is not None:
        mu = params.mu
        cvx_constraints.append(mu @ w >= constraints.return_floor)

    # Risk ceiling
    if constraints.risk_ceiling is not None:
        cov = params.cov
        cvx_constraints.append(cp.quad_form(w, cov) <= constraints.risk_ceiling ** 2)

    # Target return (per ottimizzazione min-rischio a rendimento dato)
    if constraints.target_return is not None:
        mu = params.mu
        cvx_constraints.append(mu @ w >= constraints.target_return)

    return cvx_constraints


def _make_result(
    w_val: np.ndarray,
    params: ParameterEstimate,
    objective_name: str,
    constraints: PortfolioConstraints,
    status: str,
) -> PortfolioResult:
    """Costruisce il PortfolioResult dai pesi risolti."""
    w_val = np.asarray(w_val).flatten()  # CVXPY può restituire (n,1)
    tickers = params.tickers
    weights = {t: float(w_val[i]) for i, t in enumerate(tickers)}

    # Statistiche del portafoglio
    port_return = float(params.mu @ w_val)
    port_var = float(w_val @ params.cov @ w_val)
    port_vol = float(np.sqrt(max(port_var, 0)))
    rf = get_risk_free_rate()
    sharpe = (port_return - rf) / port_vol if port_vol > 1e-10 else 0.0

    stats = {
        "expected_return": port_return,
        "volatility": port_vol,
        "sharpe_ratio": sharpe,
        "risk_free_rate": rf,
    }

    # CVaR: storico (default) con fallback parametrico
    ann_factor = params.metadata.get("ann_factor", 252)
    cvar_parametric = _parametric_cvar(port_return, port_vol)
    stats["cvar_95_parametric"] = cvar_parametric

    if params.returns is not None and len(params.returns) >= MIN_SCENARIOS_CVAR:
        port_daily_rets = params.returns @ w_val
        cvar_hist = _historical_cvar(port_daily_rets, ann_factor=ann_factor)
        stats["cvar_95"] = cvar_hist
        stats["cvar_method"] = "historical"
    else:
        stats["cvar_95"] = cvar_parametric
        stats["cvar_method"] = "parametric"

    metadata = {
        "objective": objective_name,
        "status": status,
        "constraints": {
            "long_only": constraints.long_only,
            "fully_invested": constraints.fully_invested,
            "min_weight": constraints.min_weight,
            "max_weight": constraints.max_weight,
            "group_constraints": constraints.group_constraints,
            "return_floor": constraints.return_floor,
            "risk_ceiling": constraints.risk_ceiling,
        },
    }

    return PortfolioResult(weights=weights, stats=stats, metadata=metadata)


def _handle_infeasible(
    params: ParameterEstimate,
    objective_name: str,
    constraints: PortfolioConstraints,
    status: str,
) -> PortfolioResult:
    """Gestisce il caso di problema infeasible."""
    msg = (f"Ottimizzazione {objective_name}: problema INFEASIBLE (stato: {status}). "
           f"I vincoli sono probabilmente incompatibili.")
    logger.error(msg)

    # Diagnostica
    if constraints.return_floor is not None:
        logger.error(f"  return_floor={constraints.return_floor:.2%}, "
                     f"mu range=[{params.mu.min():.2%}, {params.mu.max():.2%}]")
    if constraints.group_constraints:
        for g, (lo, hi) in constraints.group_constraints.items():
            logger.error(f"  gruppo '{g}': [{lo:.0%}, {hi:.0%}]")

    weights = {t: 0.0 for t in params.tickers}
    return PortfolioResult(
        weights=weights,
        stats={"expected_return": 0, "volatility": 0, "sharpe_ratio": 0},
        metadata={"objective": objective_name, "status": status,
                  "error": msg,
                  "constraints": {
                      "long_only": constraints.long_only,
                      "fully_invested": constraints.fully_invested,
                  }},
    )


# ============================================================
# Implementazioni degli obiettivi
# ============================================================

class MinVariance(Objective):
    """Portafoglio a minima varianza (ignora mu)."""

    @property
    def name(self) -> str:
        return "min_variance"

    def solve(self, params, constraints, asset_class_map=None):
        p = params.n_assets
        w = cp.Variable(p)
        objective = cp.Minimize(cp.quad_form(w, params.cov))
        cvx_constraints = _build_cvxpy_constraints(w, params, constraints, asset_class_map)
        prob = cp.Problem(objective, cvx_constraints)
        prob.solve(solver=cp.CLARABEL)

        if prob.status not in ("optimal", "optimal_inaccurate"):
            return _handle_infeasible(params, self.name, constraints, prob.status)

        logger.info(f"MinVariance: status={prob.status}, vol={np.sqrt(prob.value):.4f}")
        return _make_result(w.value, params, self.name, constraints, prob.status)


class MaxSharpe(Objective):
    """Portafoglio a massimo Sharpe ratio.

    Usa la trasformazione di Cornuejols-Tutuncu:
    si introduce y = w/k e k = 1/(mu-rf)^T w, e si risolve
    il problema convesso equivalente.
    """

    @property
    def name(self) -> str:
        return "max_sharpe"

    def solve(self, params, constraints, asset_class_map=None):
        p = params.n_assets
        rf = get_risk_free_rate()
        mu_excess = params.mu - rf

        # Se tutti i rendimenti in eccesso sono negativi, il max sharpe
        # non ha senso (si riduce a min variance)
        if np.all(mu_excess <= 0):
            logger.warning("MaxSharpe: tutti i rendimenti in eccesso <= 0, "
                           "uso MinVariance come fallback")
            return MinVariance().solve(params, constraints, asset_class_map)

        # Trasformazione: y = w/k, k > 0, mu_excess^T y = 1
        y = cp.Variable(p)
        k = cp.Variable(nonneg=True)
        objective = cp.Minimize(cp.quad_form(y, params.cov))

        cvx_constraints = [mu_excess @ y == 1]

        if constraints.fully_invested:
            cvx_constraints.append(cp.sum(y) == k)
        else:
            cvx_constraints.append(cp.sum(y) <= k)

        if constraints.long_only:
            cvx_constraints.append(y >= 0)

        if constraints.min_weight is not None:
            cvx_constraints.append(y >= constraints.min_weight * k)
        if constraints.max_weight is not None:
            cvx_constraints.append(y <= constraints.max_weight * k)

        # Vincoli di gruppo
        if constraints.group_constraints and asset_class_map:
            for group, (gmin, gmax) in constraints.group_constraints.items():
                indices = [
                    i for i, t in enumerate(params.tickers)
                    if asset_class_map.get(t) == group
                ]
                if indices:
                    group_sum = cp.sum(y[indices])
                    cvx_constraints.append(group_sum >= gmin * k)
                    cvx_constraints.append(group_sum <= gmax * k)

        prob = cp.Problem(objective, cvx_constraints)
        prob.solve(solver=cp.CLARABEL)

        if prob.status not in ("optimal", "optimal_inaccurate"):
            return _handle_infeasible(params, self.name, constraints, prob.status)

        k_val = k.value
        if k_val < 1e-10:
            return _handle_infeasible(params, self.name, constraints, "degenerate_k")

        w_val = y.value / k_val
        logger.info(f"MaxSharpe: status={prob.status}")
        return _make_result(w_val, params, self.name, constraints, prob.status)


class MaxReturn(Objective):
    """Massimo rendimento dato un tetto di rischio (risk_ceiling nei vincoli)."""

    @property
    def name(self) -> str:
        return "max_return"

    def solve(self, params, constraints, asset_class_map=None):
        p = params.n_assets
        w = cp.Variable(p)
        objective = cp.Maximize(params.mu @ w)
        cvx_constraints = _build_cvxpy_constraints(w, params, constraints, asset_class_map)
        prob = cp.Problem(objective, cvx_constraints)
        prob.solve(solver=cp.CLARABEL)

        if prob.status not in ("optimal", "optimal_inaccurate"):
            return _handle_infeasible(params, self.name, constraints, prob.status)

        logger.info(f"MaxReturn: status={prob.status}")
        return _make_result(w.value, params, self.name, constraints, prob.status)


class MinCVaR(Objective):
    """Minimizzazione del CVaR (Conditional Value at Risk).

    Due modalita':
    - Storica (default, quando params.returns disponibili):
      Formulazione Rockafellar-Uryasev con scenari storici reali.
      LP: min zeta + 1/(alpha*S) * sum(u_s)
           s.t. u_s >= -r_s^T w - zeta, u_s >= 0
    - Parametrica (fallback, senza scenari):
      Approssimazione gaussiana: min -mu^T w + lambda * ||L^T w||
      dove lambda = phi(z_alpha) / alpha.
    """

    def __init__(self, alpha: float = 0.05):
        self.alpha = alpha

    @property
    def name(self) -> str:
        return "min_cvar"

    def _solve_historical(self, params, constraints, asset_class_map):
        """Rockafellar-Uryasev LP con scenari storici."""
        R = params.returns  # (S, p)
        S, p = R.shape

        w = cp.Variable(p)
        zeta = cp.Variable()
        u = cp.Variable(S, nonneg=True)

        # min zeta + 1/(alpha*S) * sum(u)
        objective = cp.Minimize(zeta + (1.0 / (self.alpha * S)) * cp.sum(u))

        # u >= -R @ w - zeta (scenari di perdita)
        cvx_constraints = [u >= -R @ w - zeta]
        cvx_constraints += _build_cvxpy_constraints(
            w, params, constraints, asset_class_map
        )

        prob = cp.Problem(objective, cvx_constraints)
        prob.solve(solver=cp.CLARABEL)

        if prob.status not in ("optimal", "optimal_inaccurate"):
            return _handle_infeasible(params, self.name, constraints, prob.status)

        logger.info(f"MinCVaR (historical): status={prob.status}, "
                    f"alpha={self.alpha}, scenarios={S}")
        return _make_result(w.value, params, self.name, constraints, prob.status)

    def _solve_parametric(self, params, constraints, asset_class_map):
        """Approssimazione parametrica (gaussiana)."""
        from scipy.stats import norm

        p = params.n_assets
        z = norm.ppf(self.alpha)
        lam = norm.pdf(z) / self.alpha

        w = cp.Variable(p)
        L = np.linalg.cholesky(params.cov)
        objective = cp.Minimize(-params.mu @ w + lam * cp.norm(L.T @ w, 2))

        cvx_constraints = _build_cvxpy_constraints(
            w, params, constraints, asset_class_map
        )
        prob = cp.Problem(objective, cvx_constraints)
        prob.solve(solver=cp.CLARABEL)

        if prob.status not in ("optimal", "optimal_inaccurate"):
            return _handle_infeasible(params, self.name, constraints, prob.status)

        logger.info(f"MinCVaR (parametric): status={prob.status}, alpha={self.alpha}")
        return _make_result(w.value, params, self.name, constraints, prob.status)

    def solve(self, params, constraints, asset_class_map=None):
        if params.returns is not None and len(params.returns) >= MIN_SCENARIOS_CVAR:
            return self._solve_historical(params, constraints, asset_class_map)
        else:
            if params.returns is not None:
                logger.warning(
                    f"MinCVaR: solo {len(params.returns)} scenari "
                    f"(minimo {MIN_SCENARIOS_CVAR}), uso fallback parametrico"
                )
            return self._solve_parametric(params, constraints, asset_class_map)


class MinRiskTargetReturn(Objective):
    """Minimo rischio dato un rendimento target.

    Il target_return va impostato nei vincoli (constraints.target_return).
    """

    @property
    def name(self) -> str:
        return "min_risk_target_return"

    def solve(self, params, constraints, asset_class_map=None):
        p = params.n_assets
        w = cp.Variable(p)
        objective = cp.Minimize(cp.quad_form(w, params.cov))
        cvx_constraints = _build_cvxpy_constraints(w, params, constraints, asset_class_map)
        prob = cp.Problem(objective, cvx_constraints)
        prob.solve(solver=cp.CLARABEL)

        if prob.status not in ("optimal", "optimal_inaccurate"):
            return _handle_infeasible(params, self.name, constraints, prob.status)

        logger.info(f"MinRiskTargetReturn: status={prob.status}, "
                    f"target={constraints.target_return}")
        return _make_result(w.value, params, self.name, constraints, prob.status)


# ============================================================
# Registry
# ============================================================

OBJECTIVES: dict[str, type[Objective]] = {
    "min_variance": MinVariance,
    "max_sharpe": MaxSharpe,
    "max_return": MaxReturn,
    "min_cvar": MinCVaR,
    "min_risk_target_return": MinRiskTargetReturn,
}


def get_objective(name: str, **kwargs) -> Objective:
    """Restituisce un'istanza dell'obiettivo per nome."""
    if name not in OBJECTIVES:
        raise ValueError(
            f"Obiettivo '{name}' non trovato. Disponibili: {list(OBJECTIVES.keys())}"
        )
    return OBJECTIVES[name](**kwargs)


# ============================================================
# Validazione del risultato
# ============================================================

def validate_result(
    result: PortfolioResult,
    constraints: PortfolioConstraints,
    asset_class_map: dict[str, str] | None = None,
    tol: float = 1e-4,
) -> list[str]:
    """Valida che il risultato rispetti tutti i vincoli."""
    issues = []
    w = result.weight_array

    if not result.is_feasible():
        issues.append(f"Solver status non ottimale: {result.metadata.get('status')}")
        return issues

    # Somma pesi
    w_sum = w.sum()
    if constraints.fully_invested:
        if abs(w_sum - 1.0) > tol:
            issues.append(f"Somma pesi = {w_sum:.6f}, atteso 1.0")
    else:
        if w_sum > 1.0 + tol:
            issues.append(f"Somma pesi = {w_sum:.6f}, supera 1.0")

    # Long-only
    if constraints.long_only and np.any(w < -tol):
        neg = [(t, w_i) for t, w_i in result.weights.items() if w_i < -tol]
        issues.append(f"Pesi negativi (long-only violato): {neg}")

    # Min/max per asset
    for t, w_i in result.weights.items():
        if constraints.min_weight is not None and w_i < constraints.min_weight - tol:
            issues.append(f"{t}: peso {w_i:.4f} < min {constraints.min_weight}")
        if constraints.max_weight is not None and w_i > constraints.max_weight + tol:
            issues.append(f"{t}: peso {w_i:.4f} > max {constraints.max_weight}")

    # Vincoli di gruppo
    if constraints.group_constraints and asset_class_map:
        for group, (gmin, gmax) in constraints.group_constraints.items():
            group_w = sum(
                w_i for t, w_i in result.weights.items()
                if asset_class_map.get(t) == group
            )
            if group_w < gmin - tol:
                issues.append(f"Gruppo '{group}': peso {group_w:.4f} < min {gmin}")
            if group_w > gmax + tol:
                issues.append(f"Gruppo '{group}': peso {group_w:.4f} > max {gmax}")

    # Return floor
    if constraints.return_floor is not None:
        ret = result.stats.get("expected_return", 0)
        if ret < constraints.return_floor - tol:
            issues.append(f"Return floor violato: {ret:.4f} < {constraints.return_floor}")

    if issues:
        for issue in issues:
            logger.error(f"VALIDAZIONE: {issue}")
    else:
        logger.info("Validazione portafoglio: OK")

    return issues
