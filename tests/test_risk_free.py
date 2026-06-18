"""Test per il tasso risk-free configurabile (Ritocco 2)."""

import numpy as np
import pandas as pd
import pytest

from src.config import (
    get_risk_free_rate,
    set_risk_free_rate,
    set_risk_free_series,
    clear_risk_free_series,
)
from src.estimation import ParameterEstimate
from src.constraints import PortfolioConstraints
from src.optimizer import MinVariance, MaxSharpe
from src.strategies import compute_metrics, BuyAndHold, simulate, RebalanceEvent


@pytest.fixture(autouse=True)
def reset_risk_free():
    """Ripristina il risk-free rate dopo ogni test."""
    original = get_risk_free_rate()
    yield
    set_risk_free_rate(original)
    clear_risk_free_series()


def _make_params(p=3, seed=42):
    """ParameterEstimate sintetico."""
    rng = np.random.RandomState(seed)
    mu = np.array([0.05 + 0.03 * i for i in range(p)])
    A = rng.normal(size=(p, p)) * 0.1
    cov = A @ A.T + np.eye(p) * 0.01
    tickers = [f"A{i}" for i in range(p)]
    return ParameterEstimate(mu=mu, cov=cov, tickers=tickers)


def _make_prices(n_days=252, seed=42):
    """Prezzi sintetici per simulazione."""
    rng = np.random.RandomState(seed)
    idx = pd.bdate_range("2022-01-03", periods=n_days, name="date")
    rets = rng.normal(loc=[0.0003, 0.0002], scale=[0.01, 0.008], size=(n_days, 2))
    prices = 100 * np.cumprod(1 + rets, axis=0)
    return pd.DataFrame(prices, index=idx, columns=["A0", "A1"])


# ============================================================
# Test configurazione centralizzata
# ============================================================

class TestConfig:
    def test_default_rate(self):
        """Il default deve essere 2%."""
        assert get_risk_free_rate() == 0.02

    def test_set_rate(self):
        set_risk_free_rate(0.05)
        assert get_risk_free_rate() == 0.05

    def test_series_lookup(self):
        """Con serie storica, deve restituire il tasso piu' recente <= as_of."""
        dates = pd.to_datetime(["2020-01-01", "2021-01-01", "2022-01-01"])
        rates = pd.Series([0.01, 0.02, 0.03], index=dates)
        set_risk_free_series(rates)

        assert get_risk_free_rate(as_of="2020-06-15") == 0.01
        assert get_risk_free_rate(as_of="2021-06-15") == 0.02
        assert get_risk_free_rate(as_of="2023-01-01") == 0.03

    def test_series_fallback_to_constant(self):
        """Senza as_of, deve restituire il valore costante."""
        dates = pd.to_datetime(["2020-01-01"])
        rates = pd.Series([0.05], index=dates)
        set_risk_free_series(rates)
        set_risk_free_rate(0.03)

        # Senza data, usa il costante
        assert get_risk_free_rate() == 0.03
        # Con data, usa la serie
        assert get_risk_free_rate(as_of="2021-01-01") == 0.05

    def test_clear_series(self):
        dates = pd.to_datetime(["2020-01-01"])
        rates = pd.Series([0.05], index=dates)
        set_risk_free_series(rates)
        clear_risk_free_series()

        assert get_risk_free_rate(as_of="2021-01-01") == get_risk_free_rate()


# ============================================================
# Test Sharpe coerente nel modulo optimizer
# ============================================================

class TestSharpeOptimizer:
    def test_sharpe_uses_configured_rate(self):
        """Lo Sharpe dell'ottimizzatore deve usare il rate configurato."""
        params = _make_params()
        c = PortfolioConstraints(long_only=True)

        set_risk_free_rate(0.01)
        result_low = MinVariance().solve(params, c)

        set_risk_free_rate(0.05)
        result_high = MinVariance().solve(params, c)

        # Stesso portafoglio, ma Sharpe diverso
        assert result_low.stats["sharpe_ratio"] > result_high.stats["sharpe_ratio"]
        assert result_low.stats["risk_free_rate"] == 0.01
        assert result_high.stats["risk_free_rate"] == 0.05

    def test_sharpe_changes_coherently(self):
        """Con rf piu' alto, lo Sharpe deve diminuire (a parita' di portafoglio)."""
        params = _make_params()
        c = PortfolioConstraints(long_only=True)

        sharpes = []
        for rf in [0.0, 0.01, 0.02, 0.03, 0.05]:
            set_risk_free_rate(rf)
            result = MinVariance().solve(params, c)
            sharpes.append(result.stats["sharpe_ratio"])

        # Sharpe deve essere decrescente col risk-free
        for i in range(1, len(sharpes)):
            assert sharpes[i] <= sharpes[i - 1] + 1e-6

    def test_max_sharpe_uses_configured_rate(self):
        """MaxSharpe deve usare il rate configurato per excess returns."""
        params = _make_params()
        c = PortfolioConstraints(long_only=True)

        set_risk_free_rate(0.01)
        r1 = MaxSharpe().solve(params, c)

        set_risk_free_rate(0.04)
        r2 = MaxSharpe().solve(params, c)

        # Entrambi feasible ma Sharpe diverso
        assert r1.is_feasible()
        assert r2.is_feasible()
        assert r1.stats["risk_free_rate"] == 0.01
        assert r2.stats["risk_free_rate"] == 0.04


# ============================================================
# Test Sharpe coerente nel modulo strategies
# ============================================================

class TestSharpeStrategies:
    def test_compute_metrics_uses_rf(self):
        """compute_metrics deve usare il risk-free configurato."""
        rng = np.random.RandomState(99)
        idx = pd.bdate_range("2022-01-03", periods=253)
        # Serie con CAGR ~15% e volatilita' realistica
        daily_rets = rng.normal(0.0006, 0.01, 253)
        pv = pd.Series(
            100 * np.cumprod(1 + daily_rets),
            index=idx, name="pv",
        )

        set_risk_free_rate(0.0)
        m0 = compute_metrics(pv, [])

        set_risk_free_rate(0.05)
        m5 = compute_metrics(pv, [])

        # Lo Sharpe con rf=0 deve essere maggiore di rf=5%
        assert m0["sharpe"] > m5["sharpe"]

    def test_simulate_sharpe_consistent(self):
        """simulate() deve produrre Sharpe coerente col rf configurato."""
        prices = _make_prices()
        target = {"A0": 0.6, "A1": 0.4}

        set_risk_free_rate(0.0)
        r0 = simulate(prices, target, BuyAndHold(), tx_cost_bps=0)

        set_risk_free_rate(0.05)
        r5 = simulate(prices, target, BuyAndHold(), tx_cost_bps=0)

        assert r0.metrics["sharpe"] > r5.metrics["sharpe"]


# ============================================================
# Test: nessun hardcoded residuo
# ============================================================

class TestNoHardcoded:
    def test_no_003_in_optimizer(self):
        """Verifico che cambiando il rate, lo Sharpe non usi piu' 0.03."""
        params = _make_params()
        c = PortfolioConstraints(long_only=True)

        set_risk_free_rate(0.10)  # 10% — molto diverso da 0.03
        result = MinVariance().solve(params, c)

        ret = result.stats["expected_return"]
        vol = result.stats["volatility"]
        expected_sharpe = (ret - 0.10) / vol if vol > 1e-10 else 0.0

        np.testing.assert_allclose(
            result.stats["sharpe_ratio"], expected_sharpe, atol=1e-6,
            err_msg="Lo Sharpe non sta usando il rate configurato",
        )

    def test_stats_report_rf(self):
        """Le stats devono riportare il risk-free usato."""
        params = _make_params()
        c = PortfolioConstraints(long_only=True)

        set_risk_free_rate(0.025)
        result = MinVariance().solve(params, c)
        assert result.stats["risk_free_rate"] == 0.025
