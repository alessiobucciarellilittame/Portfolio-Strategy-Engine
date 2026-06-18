"""Test per la logica non-UI della dashboard (Fase 9)."""

import numpy as np
import pandas as pd
import pytest

from src.dashboard_data import (
    build_portfolio,
    build_profile_comparison,
    can_render_pdf,
    DashboardResult,
    ProfileComparison,
    PROFILE_ORDER,
)
from src.estimation import ParameterEstimate
from src.profiles import load_profiles, PROFILE_ORDER as PO
from src.universe import load_universe


# ============================================================
# Helper: dati sintetici (riusa il pattern dei test esistenti)
# ============================================================

def _make_params(p=10, seed=42):
    tickers = [
        "SWDA.MI", "CSSPX.MI", "SXR8.DE", "EIMI.MI",
        "IBGS.MI", "XGLE.MI", "IEAC.MI", "SGLD.MI",
        "BTC-EUR", "ETH-EUR",
    ][:p]
    mu = np.array([0.08, 0.10, 0.09, 0.06, 0.03, 0.04, 0.05, 0.12, 0.40, 0.30])[:p]
    vols = np.array([0.12, 0.13, 0.12, 0.14, 0.02, 0.06, 0.04, 0.13, 0.50, 0.55])[:p]
    rng = np.random.RandomState(seed)
    corr = np.eye(p)
    for i in range(p):
        for j in range(i + 1, p):
            if i < 4 and j < 4:
                c = 0.7
            elif 4 <= i < 7 and 4 <= j < 7:
                c = 0.6
            elif i >= 8 and j >= 8:
                c = 0.5
            else:
                c = 0.1 + rng.uniform(-0.05, 0.05)
            corr[i, j] = corr[j, i] = c
    D = np.diag(vols)
    cov = D @ corr @ D
    return ParameterEstimate(
        mu=mu, cov=cov, tickers=tickers,
        metadata={"date_start": "2015-01-02", "date_end": "2024-12-31", "ann_factor": 252},
    )


def _make_prices(tickers=None, n_days=1200, seed=42):
    if tickers is None:
        tickers = [
            "SWDA.MI", "CSSPX.MI", "SXR8.DE", "EIMI.MI",
            "IBGS.MI", "XGLE.MI", "IEAC.MI", "SGLD.MI",
            "BTC-EUR", "ETH-EUR",
        ]
    rng = np.random.RandomState(seed)
    idx = pd.bdate_range("2018-01-02", periods=n_days)
    daily_ret = rng.normal(0.0003, 0.01, (n_days, len(tickers)))
    prices = pd.DataFrame(
        100 * np.cumprod(1 + daily_ret, axis=0),
        index=idx, columns=tickers,
    )
    return prices


# ============================================================
# Test build_portfolio
# ============================================================

class TestBuildPortfolio:
    def test_basic_bilanciato(self):
        """build_portfolio deve restituire un DashboardResult valido."""
        params = _make_params()
        prices = _make_prices()
        result = build_portfolio(
            params=params,
            profile_name="bilanciato",
            horizon_years=5,
            crypto_weight=0.0,
            satellite_mode="btc",
            strategy_name="buy_and_hold",
            strategy_freq="quarterly",
            capital_eur=100_000,
            prices=prices,
        )
        assert isinstance(result, DashboardResult)
        assert result.profile_result is not None
        assert result.report.profile_name == "bilanciato"
        assert result.report.is_feasible
        assert result.core_satellite is None  # No crypto

    def test_with_crypto(self):
        """build_portfolio con cripto deve creare il core-satellite."""
        params = _make_params()
        prices = _make_prices()
        result = build_portfolio(
            params=params,
            profile_name="bilanciato",
            horizon_years=5,
            crypto_weight=0.03,
            satellite_mode="btc",
            strategy_name="periodic",
            strategy_freq="quarterly",
            capital_eur=100_000,
            prices=prices,
        )
        assert result.core_satellite is not None
        assert result.report.satellite_weight > 0

    def test_with_btc_eth(self):
        """build_portfolio con BTC+ETH satellite."""
        params = _make_params()
        prices = _make_prices()
        result = build_portfolio(
            params=params,
            profile_name="dinamico",
            horizon_years=5,
            crypto_weight=0.05,
            satellite_mode="btc_eth",
            strategy_name="periodic",
            strategy_freq="monthly",
            capital_eur=100_000,
            prices=prices,
        )
        assert result.core_satellite is not None
        sat_tickers = list(result.core_satellite.satellite_weights.keys())
        assert "ETH-EUR" in sat_tickers

    def test_backtest_present(self):
        """Con prezzi sufficienti, il backtest deve essere presente."""
        params = _make_params()
        prices = _make_prices()
        result = build_portfolio(
            params=params,
            profile_name="moderato",
            horizon_years=5,
            crypto_weight=0.0,
            satellite_mode="btc",
            strategy_name="periodic",
            strategy_freq="quarterly",
            capital_eur=100_000,
            prices=prices,
        )
        assert result.strategy_result is not None
        assert result.report.backtest_cagr is not None

    def test_cost_breakdown_present(self):
        """Con backtest, il cost breakdown deve essere presente."""
        params = _make_params()
        prices = _make_prices()
        result = build_portfolio(
            params=params,
            profile_name="bilanciato",
            horizon_years=5,
            crypto_weight=0.0,
            satellite_mode="btc",
            strategy_name="periodic",
            strategy_freq="quarterly",
            capital_eur=100_000,
            prices=prices,
        )
        assert result.cost_breakdown is not None
        assert result.tax_breakdown is not None
        assert np.isfinite(result.cost_breakdown.cagr_gross)
        assert np.isfinite(result.cost_breakdown.cagr_net_costs)
        assert np.isfinite(result.tax_breakdown.cagr_net_tax)

    def test_report_matches_engine(self):
        """I numeri nel report devono combaciare con gli oggetti del motore."""
        params = _make_params()
        prices = _make_prices()
        result = build_portfolio(
            params=params,
            profile_name="bilanciato",
            horizon_years=5,
            crypto_weight=0.0,
            satellite_mode="btc",
            strategy_name="buy_and_hold",
            strategy_freq="quarterly",
            capital_eur=100_000,
            prices=prices,
        )
        pr = result.profile_result
        report = result.report

        # Stats devono corrispondere
        np.testing.assert_allclose(
            report.expected_return,
            pr.portfolio.stats["expected_return"],
            atol=1e-6,
        )
        np.testing.assert_allclose(
            report.expected_volatility,
            pr.portfolio.stats["volatility"],
            atol=1e-6,
        )

    def test_all_profiles_feasible(self):
        """Tutti i 5 profili devono produrre portafogli fattibili."""
        params = _make_params()
        prices = _make_prices()
        for name in PROFILE_ORDER:
            result = build_portfolio(
                params=params,
                profile_name=name,
                horizon_years=5,
                crypto_weight=0.0,
                satellite_mode="btc",
                strategy_name="buy_and_hold",
                strategy_freq="quarterly",
                capital_eur=100_000,
                prices=prices,
            )
            assert result.report.is_feasible, f"Profilo {name} non fattibile"

    def test_horizon_affects_vol_ceiling(self):
        """Orizzonti diversi devono produrre vol ceiling effettivi diversi."""
        params = _make_params()
        prices = _make_prices()

        r_short = build_portfolio(params, "bilanciato", 2, 0, "btc", "buy_and_hold", "quarterly", 100_000, prices)
        r_long = build_portfolio(params, "bilanciato", 10, 0, "btc", "buy_and_hold", "quarterly", 100_000, prices)

        assert r_short.report.effective_vol_ceiling < r_long.report.effective_vol_ceiling


# ============================================================
# Test confronto profili
# ============================================================

class TestProfileComparison:
    def test_five_profiles(self):
        """Il confronto deve includere tutti e 5 i profili."""
        params = _make_params()
        prices = _make_prices()
        comp = build_profile_comparison(params, 5, prices)
        assert isinstance(comp, ProfileComparison)
        assert len(comp.names) == 5
        for name in PROFILE_ORDER:
            assert name in comp.names

    def test_volatility_monotonic(self):
        """La volatilita' deve essere monotona crescente."""
        params = _make_params()
        prices = _make_prices()
        comp = build_profile_comparison(params, 5, prices)
        for i in range(len(comp.volatilities) - 1):
            assert comp.volatilities[i] <= comp.volatilities[i + 1] + 0.01

    def test_class_allocations_sum_to_one(self):
        """Le allocazioni per classe devono sommare a ~1."""
        params = _make_params()
        prices = _make_prices()
        comp = build_profile_comparison(params, 5, prices)
        for ca in comp.class_allocations:
            total = sum(ca.values())
            assert abs(total - 1.0) < 0.01, f"Allocazione per classe somma a {total}"


# ============================================================
# Test PDF availability
# ============================================================

class TestPdfAvailability:
    def test_can_render_pdf_is_bool(self):
        """can_render_pdf deve restituire un booleano."""
        result = can_render_pdf()
        assert isinstance(result, bool)
