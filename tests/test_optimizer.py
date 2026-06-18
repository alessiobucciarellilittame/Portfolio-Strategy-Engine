"""Test per il motore di ottimizzazione (Fase 3)."""

import numpy as np
import pytest

from src.estimation import ParameterEstimate
from src.constraints import PortfolioConstraints
from src.optimizer import (
    MinVariance,
    MaxSharpe,
    MaxReturn,
    MinCVaR,
    MinRiskTargetReturn,
    get_objective,
    validate_result,
)
from src.config import get_risk_free_rate
from src.frontier import compute_frontier


def _make_params(p=3, seed=42):
    """Crea ParameterEstimate sintetico per i test."""
    rng = np.random.RandomState(seed)
    # Rendimenti attesi crescenti: 5%, 8%, 11%, 14%, ...
    mu = np.array([0.05 + 0.03 * i for i in range(p)])
    # Covarianza: genero una matrice PSD
    A = rng.normal(size=(p, p)) * 0.1
    cov = A @ A.T + np.eye(p) * 0.01  # PSD garantita
    tickers = [f"A{i}" for i in range(p)]
    return ParameterEstimate(mu=mu, cov=cov, tickers=tickers)


def _make_params_2asset():
    """2 asset con soluzione analitica nota per min-variance.

    Asset 0: vol=10%, Asset 1: vol=20%, correlazione=0.
    Min-variance analitico (long-only, fully invested, uncorrelated):
        w0 = var1/(var0+var1) = 0.04/0.05 = 0.8
        w1 = var0/(var0+var1) = 0.01/0.05 = 0.2
    """
    mu = np.array([0.06, 0.12])
    cov = np.array([
        [0.01, 0.00],  # vol=10%
        [0.00, 0.04],  # vol=20%
    ])
    return ParameterEstimate(mu=mu, cov=cov, tickers=["X", "Y"])


# ============================================================
# Test correttezza numerica
# ============================================================

class TestMinVariance:
    def test_2asset_analytic(self):
        """Verifica la soluzione analitica a 2 asset non correlati."""
        params = _make_params_2asset()
        c = PortfolioConstraints(long_only=True)
        result = MinVariance().solve(params, c)

        assert result.is_feasible()
        np.testing.assert_allclose(result.weights["X"], 0.8, atol=1e-3)
        np.testing.assert_allclose(result.weights["Y"], 0.2, atol=1e-3)

    def test_vol_less_than_equal_weight(self):
        """Min-variance deve avere volatilità <= portafoglio equipesato."""
        params = _make_params(p=5)
        c = PortfolioConstraints(long_only=True)
        result = MinVariance().solve(params, c)

        assert result.is_feasible()
        # Portafoglio equipesato
        w_eq = np.ones(5) / 5
        vol_eq = np.sqrt(w_eq @ params.cov @ w_eq)
        assert result.stats["volatility"] <= vol_eq + 1e-6

    def test_weights_sum_to_one(self):
        params = _make_params()
        result = MinVariance().solve(params, PortfolioConstraints())
        assert abs(sum(result.weights.values()) - 1.0) < 1e-4


class TestMaxSharpe:
    def test_feasible(self):
        params = _make_params()
        result = MaxSharpe().solve(params, PortfolioConstraints())
        assert result.is_feasible()
        assert abs(sum(result.weights.values()) - 1.0) < 1e-4

    def test_sharpe_ge_min_variance(self):
        """Max Sharpe deve avere Sharpe >= min variance."""
        params = _make_params()
        c = PortfolioConstraints(long_only=True)
        mv = MinVariance().solve(params, c)
        ms = MaxSharpe().solve(params, c)

        assert ms.stats["sharpe_ratio"] >= mv.stats["sharpe_ratio"] - 1e-3


class TestMaxReturn:
    def test_concentrates_on_best_asset(self):
        """Senza vincoli di max_weight, max return concentra sul miglior asset."""
        params = _make_params()
        c = PortfolioConstraints(long_only=True, max_weight=1.0)
        result = MaxReturn().solve(params, c)

        assert result.is_feasible()
        # L'asset con mu più alto (A2=15%) deve avere il peso maggiore
        best_idx = np.argmax(params.mu)
        best_ticker = params.tickers[best_idx]
        assert result.weights[best_ticker] > 0.99


class TestMinCVaR:
    def test_feasible(self):
        params = _make_params()
        result = MinCVaR().solve(params, PortfolioConstraints())
        assert result.is_feasible()
        assert abs(sum(result.weights.values()) - 1.0) < 1e-4


class TestMinRiskTargetReturn:
    def test_meets_target(self):
        params = _make_params()
        c = PortfolioConstraints(long_only=True, target_return=0.10)
        result = MinRiskTargetReturn().solve(params, c)

        assert result.is_feasible()
        assert result.stats["expected_return"] >= 0.10 - 1e-4


# ============================================================
# Test vincoli
# ============================================================

class TestConstraints:
    def test_long_only(self):
        params = _make_params()
        c = PortfolioConstraints(long_only=True)
        result = MinVariance().solve(params, c)

        for w in result.weights.values():
            assert w >= -1e-4

    def test_max_weight(self):
        params = _make_params()
        c = PortfolioConstraints(long_only=True, max_weight=0.30)
        result = MaxReturn().solve(params, c)

        for w in result.weights.values():
            assert w <= 0.30 + 1e-4

    def test_group_constraint(self):
        """Vincolo di gruppo: 'high' <= 40%."""
        params = _make_params(p=4)
        ac_map = {"A0": "low", "A1": "low", "A2": "high", "A3": "high"}
        c = PortfolioConstraints(
            long_only=True,
            group_constraints={"high": (0.0, 0.40)},
        )
        result = MaxReturn().solve(params, c, asset_class_map=ac_map)

        assert result.is_feasible()
        high_total = result.weights["A2"] + result.weights["A3"]
        assert high_total <= 0.40 + 1e-4

    def test_return_floor(self):
        params = _make_params()
        c = PortfolioConstraints(long_only=True, return_floor=0.08)
        result = MinVariance().solve(params, c)

        assert result.is_feasible()
        assert result.stats["expected_return"] >= 0.08 - 1e-4

    def test_not_fully_invested(self):
        """Con fully_invested=False, la somma pesi può essere < 1."""
        params = _make_params()
        c = PortfolioConstraints(long_only=True, fully_invested=False, risk_ceiling=0.01)
        result = MinVariance().solve(params, c)
        # Con risk ceiling molto basso, il solver terrà liquidità
        if result.is_feasible():
            assert sum(result.weights.values()) <= 1.0 + 1e-4


class TestInfeasible:
    def test_impossible_return_floor(self):
        """Un return floor impossibilmente alto deve dare infeasible."""
        params = _make_params()
        c = PortfolioConstraints(long_only=True, return_floor=10.0)  # 1000%
        result = MinVariance().solve(params, c)

        assert not result.is_feasible()
        assert "error" in result.metadata or result.metadata["status"] != "optimal"

    def test_contradictory_group_constraints(self):
        """Vincoli di gruppo contraddittori: tutti i gruppi sommano > 1."""
        params = _make_params(p=3)
        ac_map = {"A0": "x", "A1": "y", "A2": "z"}
        c = PortfolioConstraints(
            long_only=True,
            group_constraints={
                "x": (0.5, 1.0),
                "y": (0.5, 1.0),
                "z": (0.5, 1.0),
            },
        )
        result = MinVariance().solve(params, c, asset_class_map=ac_map)
        assert not result.is_feasible()


# ============================================================
# Test validazione
# ============================================================

class TestValidation:
    def test_valid_result_passes(self):
        params = _make_params()
        c = PortfolioConstraints(long_only=True, max_weight=0.50)
        result = MinVariance().solve(params, c)
        issues = validate_result(result, c)
        assert len(issues) == 0

    def test_group_validation(self):
        params = _make_params(p=4)
        ac_map = {"A0": "a", "A1": "a", "A2": "b", "A3": "b"}
        c = PortfolioConstraints(
            long_only=True,
            group_constraints={"b": (0.0, 0.30)},
        )
        result = MaxReturn().solve(params, c, asset_class_map=ac_map)
        issues = validate_result(result, c, asset_class_map=ac_map)
        assert len(issues) == 0


# ============================================================
# Test registry
# ============================================================

class TestRegistry:
    def test_all_objectives(self):
        for name in ["min_variance", "max_sharpe", "max_return", "min_cvar",
                      "min_risk_target_return"]:
            obj = get_objective(name)
            assert obj.name == name

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="non trovato"):
            get_objective("nonexistent")


# ============================================================
# Test frontiera efficiente
# ============================================================

class TestFrontier:
    def test_frontier_monotonic(self):
        """Sulla frontiera, rendimento crescente -> rischio crescente."""
        params = _make_params(p=4)
        c = PortfolioConstraints(long_only=True)
        frontier = compute_frontier(params, c, n_points=15)

        assert frontier.n_points >= 5
        # Rendimenti devono essere (approssimativamente) crescenti
        for i in range(1, len(frontier.returns)):
            assert frontier.returns[i] >= frontier.returns[i - 1] - 1e-4
        # Volatilità devono essere (approssimativamente) crescenti
        for i in range(1, len(frontier.volatilities)):
            assert frontier.volatilities[i] >= frontier.volatilities[i - 1] - 1e-3

    def test_frontier_nonempty(self):
        params = _make_params()
        c = PortfolioConstraints(long_only=True)
        frontier = compute_frontier(params, c, n_points=10)
        assert frontier.n_points > 0
        assert len(frontier.portfolios) > 0
