"""Test per gli stimatori della matrice di covarianza."""

import numpy as np
import pandas as pd
import pytest

from src.cov_estimators import (
    SampleCovariance,
    LedoitWolfCovariance,
    OASCovariance,
    get_cov_estimator,
)


def _make_returns(n=500, p=5, seed=42):
    """Genera rendimenti sintetici con covarianza nota."""
    rng = np.random.RandomState(seed)
    data = rng.normal(loc=0, scale=0.01, size=(n, p))
    idx = pd.bdate_range("2022-01-03", periods=n, name="date")
    cols = [f"A{i}" for i in range(p)]
    return pd.DataFrame(data, index=idx, columns=cols)


class TestSampleCovariance:
    def test_symmetric(self):
        ret = _make_returns()
        est = SampleCovariance().estimate(ret, ann_factor=252)
        assert np.allclose(est.cov, est.cov.T)

    def test_psd(self):
        """La covarianza campionaria deve essere PSD."""
        ret = _make_returns()
        est = SampleCovariance().estimate(ret, ann_factor=252)
        eigenvalues = np.linalg.eigvalsh(est.cov)
        assert eigenvalues.min() >= -1e-10

    def test_annualization(self):
        """Cov annualizzata = cov giornaliera × ann_factor."""
        ret = _make_returns()
        ann = 252
        est = SampleCovariance().estimate(ret, ann_factor=ann)
        cov_daily = ret.cov().values
        np.testing.assert_allclose(est.cov, cov_daily * ann, atol=1e-12)

    def test_annualization_synthetic_known(self):
        """Test con volatilità esatta nota.

        Se i rendimenti hanno std=0.01 giornaliero e sono indipendenti,
        la varianza annualizzata = 0.01^2 * 252 = 0.0252
        e la vol annualizzata = sqrt(0.0252) ≈ 0.1587 (circa 15.87%).
        """
        n = 100_000  # Tanti dati per convergere
        rng = np.random.RandomState(99)
        data = rng.normal(0, 0.01, size=(n, 1))
        idx = pd.RangeIndex(n, name="obs")
        ret = pd.DataFrame(data, index=idx, columns=["X"])

        est = SampleCovariance().estimate(ret, ann_factor=252)
        var_ann = est.cov[0, 0]
        vol_ann = np.sqrt(var_ann)

        # Con 100k campioni, la stima deve essere molto vicina al valore teorico
        expected_var = 0.01**2 * 252  # 0.0252
        assert abs(var_ann - expected_var) < 0.001, (
            f"Varianza annualizzata {var_ann:.6f} vs attesa {expected_var:.6f}"
        )
        assert abs(vol_ann - np.sqrt(expected_var)) < 0.005

    def test_shrinkage_is_zero(self):
        ret = _make_returns()
        est = SampleCovariance().estimate(ret, ann_factor=252)
        assert est.shrinkage_intensity == 0.0


class TestLedoitWolf:
    def test_psd(self):
        ret = _make_returns()
        est = LedoitWolfCovariance().estimate(ret, ann_factor=252)
        eigenvalues = np.linalg.eigvalsh(est.cov)
        assert eigenvalues.min() >= -1e-10

    def test_shrinkage_in_range(self):
        ret = _make_returns()
        est = LedoitWolfCovariance().estimate(ret, ann_factor=252)
        assert 0.0 <= est.shrinkage_intensity <= 1.0

    def test_better_conditioning_than_sample(self):
        """Il Ledoit-Wolf deve avere condition number <= sample."""
        ret = _make_returns(n=50, p=10)  # p grande vs n -> sample mal condizionata
        sample = SampleCovariance().estimate(ret, ann_factor=252)
        lw = LedoitWolfCovariance().estimate(ret, ann_factor=252)
        assert lw.condition_number <= sample.condition_number + 1e-6

    def test_symmetric(self):
        ret = _make_returns()
        est = LedoitWolfCovariance().estimate(ret, ann_factor=252)
        assert np.allclose(est.cov, est.cov.T)


class TestOAS:
    def test_psd(self):
        ret = _make_returns()
        est = OASCovariance().estimate(ret, ann_factor=252)
        eigenvalues = np.linalg.eigvalsh(est.cov)
        assert eigenvalues.min() >= -1e-10

    def test_shrinkage_in_range(self):
        ret = _make_returns()
        est = OASCovariance().estimate(ret, ann_factor=252)
        assert 0.0 <= est.shrinkage_intensity <= 1.0

    def test_symmetric(self):
        ret = _make_returns()
        est = OASCovariance().estimate(ret, ann_factor=252)
        assert np.allclose(est.cov, est.cov.T)


class TestRegistry:
    def test_get_known_estimator(self):
        for name in ["sample", "ledoit_wolf", "oas"]:
            est = get_cov_estimator(name)
            assert est.name == name

    def test_get_unknown_raises(self):
        with pytest.raises(ValueError, match="non trovato"):
            get_cov_estimator("nonexistent")
