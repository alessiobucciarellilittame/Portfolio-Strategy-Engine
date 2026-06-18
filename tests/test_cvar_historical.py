"""Test per il CVaR storico (Ritocco 1)."""

import numpy as np
import pytest

from src.estimation import ParameterEstimate
from src.constraints import PortfolioConstraints
from src.optimizer import (
    MinCVaR,
    MinVariance,
    MaxReturn,
    _historical_cvar,
    _parametric_cvar,
    _make_result,
)


def _make_params_with_returns(p=3, n_scenarios=500, seed=42, fat_tails=False):
    """ParameterEstimate con rendimenti storici.

    Se fat_tails=True, usa una distribuzione t di Student (nu=3)
    per simulare code grasse (tipico di crypto/crash azionari).
    """
    rng = np.random.RandomState(seed)

    # Genera drift e vol per p asset
    drifts = np.array([0.0003 - 0.0001 * i for i in range(p)])
    scales = np.array([0.01 + 0.005 * i for i in range(p)])

    if fat_tails:
        daily_rets = rng.standard_t(df=3, size=(n_scenarios, p))
        for i in range(p):
            daily_rets[:, i] = daily_rets[:, i] * scales[i] + drifts[i]
        # L'ultimo asset ha vol 3x (crypto-like)
        if p >= 3:
            daily_rets[:, -1] *= 3
    else:
        daily_rets = np.column_stack([
            rng.normal(loc=drifts[i], scale=scales[i], size=n_scenarios)
            for i in range(p)
        ])

    mu = daily_rets.mean(axis=0) * 252
    cov = np.cov(daily_rets, rowvar=False) * 252
    tickers = [f"A{i}" for i in range(p)]

    return ParameterEstimate(
        mu=mu, cov=cov, tickers=tickers,
        returns=daily_rets,
        metadata={"ann_factor": 252},
    )


def _make_params_no_returns(p=3, seed=42):
    """ParameterEstimate SENZA rendimenti (fallback parametrico)."""
    rng = np.random.RandomState(seed)
    mu = np.array([0.05 + 0.03 * i for i in range(p)])
    A = rng.normal(size=(p, p)) * 0.1
    cov = A @ A.T + np.eye(p) * 0.01
    tickers = [f"A{i}" for i in range(p)]
    return ParameterEstimate(mu=mu, cov=cov, tickers=tickers)


# ============================================================
# Test calcolo CVaR storico
# ============================================================

class TestHistoricalCVaR:
    def test_positive_for_risky_portfolio(self):
        """Il CVaR storico deve essere positivo per portafogli rischiosi."""
        rng = np.random.RandomState(42)
        daily_rets = rng.normal(loc=0.0003, scale=0.01, size=500)
        cvar = _historical_cvar(daily_rets)
        assert cvar > 0

    def test_higher_vol_higher_cvar(self):
        """Asset piu' volatile deve avere CVaR piu' alto."""
        rng = np.random.RandomState(42)
        rets_low_vol = rng.normal(0, 0.005, 1000)
        rets_high_vol = rng.normal(0, 0.02, 1000)
        assert _historical_cvar(rets_high_vol) > _historical_cvar(rets_low_vol)

    def test_fat_tails_worse_than_gaussian_predicts(self):
        """Su distribuzione con crash, la coda empirica e' peggiore
        di quanto il modello gaussiano preveda.

        Confronto a livello giornaliero (nessuna annualizzazione):
        la media della coda storica e' piu' negativa della previsione
        gaussiana basata su media e std campionarie.
        """
        rng = np.random.RandomState(42)
        n = 5000

        # Rendimenti normali + crash occasionali (5% dei giorni)
        rets = rng.normal(loc=0.0003, scale=0.01, size=n)
        n_crash = int(n * 0.05)
        crash_idx = rng.choice(n, n_crash, replace=False)
        rets[crash_idx] = rng.normal(loc=-0.04, scale=0.02, size=n_crash)

        mu_d = float(np.mean(rets))
        sigma_d = float(np.std(rets))
        alpha = 0.05

        # Coda empirica: media dei peggiori 5%
        cutoff = int(np.floor(n * alpha))
        sorted_rets = np.sort(rets)
        empirical_tail_mean = float(np.mean(sorted_rets[:cutoff]))

        # Previsione gaussiana della coda
        from scipy.stats import norm
        z = norm.ppf(alpha)
        gaussian_tail_mean = mu_d + sigma_d * norm.expect(
            lambda x: x, loc=0, scale=1, lb=-np.inf, ub=z
        ) / alpha
        # Semplificazione: gaussian_tail_mean = mu_d - sigma_d * phi(z)/alpha
        gaussian_tail_mean_simple = mu_d - sigma_d * norm.pdf(z) / alpha

        # La coda empirica deve essere PIU' NEGATIVA (perdite peggiori)
        assert empirical_tail_mean < gaussian_tail_mean_simple, (
            f"Coda empirica {empirical_tail_mean:.6f} >= "
            f"previsione gaussiana {gaussian_tail_mean_simple:.6f}"
        )

    def test_normal_cvar_reasonable(self):
        """Su dati normali, il CVaR storico deve essere positivo e ragionevole.

        L'annualizzazione (sqrt(252) per storico vs formula analitica per
        parametrico) produce valori leggermente diversi per costruzione,
        ma lo storico deve essere nello stesso ordine di grandezza.
        """
        rng = np.random.RandomState(42)
        n = 10000
        rets = rng.normal(0.0003, 0.01, n)

        cvar_hist = _historical_cvar(rets)

        # Deve essere positivo e ragionevole (10-50% annualizzato per vol ~16%)
        assert 0.05 < cvar_hist < 1.0, f"CVaR storico fuori range: {cvar_hist:.4f}"

    def test_few_scenarios_uses_all(self):
        """Con pochi scenari, il cutoff deve usare almeno 1 osservazione."""
        rets = np.array([-0.05, -0.02, 0.01, 0.03, 0.04])
        cvar = _historical_cvar(rets, alpha=0.05, ann_factor=252)
        # Con 5 scenari e alpha=0.05: floor(5*0.05)=0 -> max(1,0)=1
        # Deve usare il peggior rendimento: -0.05
        expected = 0.05 * np.sqrt(252)
        np.testing.assert_allclose(cvar, expected, rtol=1e-10)


# ============================================================
# Test CVaR nelle statistiche del portafoglio
# ============================================================

class TestCVaRInStats:
    def test_stats_include_both_cvars(self):
        """Le stats devono includere sia CVaR storico che parametrico."""
        params = _make_params_with_returns()
        c = PortfolioConstraints(long_only=True)
        result = MinVariance().solve(params, c)
        assert result.is_feasible()
        assert "cvar_95" in result.stats
        assert "cvar_95_parametric" in result.stats
        assert result.stats["cvar_method"] == "historical"

    def test_fallback_parametric_without_returns(self):
        """Senza rendimenti, deve usare il fallback parametrico."""
        params = _make_params_no_returns()
        c = PortfolioConstraints(long_only=True)
        result = MinVariance().solve(params, c)
        assert result.is_feasible()
        assert result.stats["cvar_method"] == "parametric"
        # cvar_95 e cvar_95_parametric devono coincidere
        np.testing.assert_allclose(
            result.stats["cvar_95"],
            result.stats["cvar_95_parametric"],
        )

    def test_cvar_captures_tail_for_fat_tails(self):
        """Con code grasse, la coda empirica del portafoglio e' peggiore
        di quanto il modello gaussiano preveda (a livello giornaliero)."""
        params = _make_params_with_returns(fat_tails=True, n_scenarios=5000)
        c = PortfolioConstraints(long_only=True)
        result = MinVariance().solve(params, c)
        assert result.is_feasible()

        # Calcola i rendimenti giornalieri del portafoglio
        w = np.array([result.weights[t] for t in params.tickers])
        port_daily = params.returns @ w

        # Confronto coda empirica vs gaussiana a livello giornaliero
        alpha = 0.05
        cutoff = max(1, int(np.floor(len(port_daily) * alpha)))
        empirical_tail = float(np.mean(np.sort(port_daily)[:cutoff]))

        from scipy.stats import norm
        mu_d = float(np.mean(port_daily))
        sigma_d = float(np.std(port_daily))
        z = norm.ppf(alpha)
        gaussian_tail = mu_d - sigma_d * norm.pdf(z) / alpha

        # La coda empirica deve essere piu' negativa
        assert empirical_tail < gaussian_tail, (
            f"Coda empirica {empirical_tail:.6f} >= "
            f"previsione gaussiana {gaussian_tail:.6f}"
        )


# ============================================================
# Test MinCVaR (ottimizzazione)
# ============================================================

class TestMinCVaROptimization:
    def test_feasible_with_returns(self):
        """MinCVaR con scenari storici deve essere feasible."""
        params = _make_params_with_returns()
        c = PortfolioConstraints(long_only=True)
        result = MinCVaR().solve(params, c)
        assert result.is_feasible()
        assert abs(sum(result.weights.values()) - 1.0) < 1e-4

    def test_feasible_without_returns(self):
        """MinCVaR senza scenari deve fare fallback parametrico."""
        params = _make_params_no_returns()
        c = PortfolioConstraints(long_only=True)
        result = MinCVaR().solve(params, c)
        assert result.is_feasible()

    def test_constraints_respected(self):
        """MinCVaR storico deve rispettare tutti i vincoli."""
        params = _make_params_with_returns(p=4, n_scenarios=500)
        ac_map = {"A0": "low", "A1": "low", "A2": "high", "A3": "high"}
        c = PortfolioConstraints(
            long_only=True,
            max_weight=0.40,
            group_constraints={"high": (0.0, 0.50)},
        )
        result = MinCVaR().solve(params, c, asset_class_map=ac_map)
        assert result.is_feasible()

        for w in result.weights.values():
            assert w >= -1e-4
            assert w <= 0.40 + 1e-4

        high_w = result.weights["A2"] + result.weights["A3"]
        assert high_w <= 0.50 + 1e-4

    def test_long_only_respected(self):
        """MinCVaR storico: nessun peso negativo."""
        params = _make_params_with_returns()
        c = PortfolioConstraints(long_only=True)
        result = MinCVaR().solve(params, c)
        for w in result.weights.values():
            assert w >= -1e-4

    def test_historical_reduces_tail_risk(self):
        """MinCVaR storico deve produrre portafoglio con CVaR basso."""
        params = _make_params_with_returns(fat_tails=True, n_scenarios=1000)
        c = PortfolioConstraints(long_only=True)

        result_cvar = MinCVaR().solve(params, c)
        result_maxret = MaxReturn().solve(params, c)

        assert result_cvar.is_feasible()
        assert result_maxret.is_feasible()

        # MinCVaR deve avere CVaR <= MaxReturn
        assert result_cvar.stats["cvar_95"] <= result_maxret.stats["cvar_95"] + 1e-3
