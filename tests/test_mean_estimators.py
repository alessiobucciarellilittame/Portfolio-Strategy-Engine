"""Test per gli stimatori di rendimenti attesi (mu)."""

import numpy as np
import pandas as pd
import pytest

from src.mean_estimators import (
    HistoricalMean,
    JamesSteinMean,
    BayesSteinMean,
    get_mean_estimator,
)


def _make_returns(n=500, p=5, seed=42):
    """Genera rendimenti sintetici con media e volatilità note."""
    rng = np.random.RandomState(seed)
    # Medie giornaliere diverse per asset
    daily_means = np.array([0.0002, 0.0004, 0.0001, 0.0003, 0.0005])[:p]
    daily_std = 0.01
    data = rng.normal(loc=daily_means, scale=daily_std, size=(n, p))
    idx = pd.bdate_range("2022-01-03", periods=n, name="date")
    cols = [f"A{i}" for i in range(p)]
    return pd.DataFrame(data, index=idx, columns=cols), daily_means


class TestHistoricalMean:
    def test_annualization(self):
        """Verifica che la media annualizzata = media giornaliera × ann_factor."""
        ret, daily_means = _make_returns(n=1000, p=3)
        est = HistoricalMean().estimate(ret, ann_factor=252)

        # Con 1000 osservazioni, la media campionaria deve essere vicina alla vera
        expected_ann = ret.mean().values * 252
        np.testing.assert_allclose(est.mu, expected_ann, atol=1e-10)

    def test_shrinkage_is_zero(self):
        ret, _ = _make_returns()
        est = HistoricalMean().estimate(ret, ann_factor=252)
        assert est.shrinkage_intensity == 0.0

    def test_annualization_synthetic_known_value(self):
        """Test con valore esatto noto: media costante -> annualizzazione esatta."""
        # Rendimenti costanti = 0.001 giornaliero -> 0.252 annualizzato (252 gg)
        n, p = 100, 2
        data = np.full((n, p), 0.001)
        idx = pd.bdate_range("2023-01-02", periods=n, name="date")
        ret = pd.DataFrame(data, index=idx, columns=["X", "Y"])

        est = HistoricalMean().estimate(ret, ann_factor=252)
        np.testing.assert_allclose(est.mu, [0.252, 0.252], atol=1e-10)


class TestJamesStein:
    def test_shrinkage_in_range(self):
        """L'intensità di shrinkage deve essere in [0, 1]."""
        ret, _ = _make_returns()
        est = JamesSteinMean().estimate(ret, ann_factor=252)
        assert 0.0 <= est.shrinkage_intensity <= 1.0

    def test_shrinkage_toward_grand_mean(self):
        """La stima JS deve essere tra la media campionaria e la grand mean."""
        ret, _ = _make_returns()
        hist = HistoricalMean().estimate(ret, ann_factor=252)
        js = JamesSteinMean().estimate(ret, ann_factor=252)

        grand_mean = hist.mu.mean()
        # Ogni componente di JS deve essere tra la componente storica e la grand mean
        for i in range(len(js.mu)):
            lo = min(hist.mu[i], grand_mean)
            hi = max(hist.mu[i], grand_mean)
            assert lo - 1e-10 <= js.mu[i] <= hi + 1e-10, (
                f"JS mu[{i}]={js.mu[i]:.6f} non è tra "
                f"hist={hist.mu[i]:.6f} e grand_mean={grand_mean:.6f}"
            )


class TestBayesStein:
    def test_shrinkage_in_range(self):
        ret, _ = _make_returns()
        est = BayesSteinMean().estimate(ret, ann_factor=252)
        assert 0.0 <= est.shrinkage_intensity <= 1.0

    def test_output_shape(self):
        ret, _ = _make_returns(p=4)
        est = BayesSteinMean().estimate(ret, ann_factor=252)
        assert est.mu.shape == (4,)
        assert len(est.tickers) == 4


class TestRegistry:
    def test_get_known_estimator(self):
        for name in ["historical", "james_stein", "bayes_stein"]:
            est = get_mean_estimator(name)
            assert est.name == name

    def test_get_unknown_raises(self):
        with pytest.raises(ValueError, match="non trovato"):
            get_mean_estimator("nonexistent")
