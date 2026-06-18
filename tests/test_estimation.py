"""Test per la pipeline di stima dei parametri."""

import numpy as np
import pandas as pd
import pytest
from datetime import date

from src.estimation import (
    estimate_parameters,
    prepare_returns,
    infer_ann_factor,
    validate_estimates,
)
from src.mean_estimators import HistoricalMean
from src.cov_estimators import SampleCovariance


def _make_returns(n=500, p=4, seed=42):
    rng = np.random.RandomState(seed)
    data = rng.normal(loc=0.0003, scale=0.01, size=(n, p))
    idx = pd.bdate_range("2022-01-03", periods=n, name="date")
    cols = [f"T{i}" for i in range(p)]
    return pd.DataFrame(data, index=idx, columns=cols)


class TestPrepareReturns:
    def test_as_of_no_lookahead(self):
        """I rendimenti dopo as_of devono essere esclusi."""
        ret = _make_returns()
        cutoff = date(2022, 6, 1)
        prepared = prepare_returns(ret, as_of=cutoff)
        assert prepared.index.max() <= pd.Timestamp(cutoff)

    def test_window(self):
        """La finestra deve limitare il numero di osservazioni."""
        ret = _make_returns(n=500)
        prepared = prepare_returns(ret, window_days=100)
        assert len(prepared) == 100

    def test_drops_nan(self):
        """NaN devono essere rimossi."""
        ret = _make_returns(n=10)
        ret.iloc[0] = np.nan
        prepared = prepare_returns(ret)
        assert not prepared.isna().any().any()


class TestInferAnnFactor:
    def test_business_days(self):
        idx = pd.bdate_range("2023-01-02", periods=100, name="date")
        ret = pd.DataFrame({"A": range(100)}, index=idx)
        assert infer_ann_factor(ret) == 252

    def test_weekly(self):
        idx = pd.date_range("2023-01-02", periods=100, freq="W", name="date")
        ret = pd.DataFrame({"A": range(100)}, index=idx)
        assert infer_ann_factor(ret) == 52


class TestEstimateParameters:
    def test_output_shapes(self):
        ret = _make_returns(p=4)
        est = estimate_parameters(ret, mean_method="historical", cov_method="sample")
        assert est.mu.shape == (4,)
        assert est.cov.shape == (4, 4)
        assert len(est.tickers) == 4

    def test_all_combinations(self):
        """Tutte le combinazioni stimatore mu × stimatore cov devono funzionare."""
        ret = _make_returns()
        for mm in ["historical", "james_stein", "bayes_stein"]:
            for cm in ["sample", "ledoit_wolf", "oas"]:
                est = estimate_parameters(ret, mean_method=mm, cov_method=cm)
                assert est.mu.shape == (len(ret.columns),)
                assert est.cov.shape == (len(ret.columns), len(ret.columns))

    def test_metadata_present(self):
        ret = _make_returns()
        est = estimate_parameters(ret, mean_method="james_stein", cov_method="ledoit_wolf")
        assert "mean_method" in est.metadata
        assert "cov_method" in est.metadata
        assert "ann_factor" in est.metadata
        assert "mean_shrinkage" in est.metadata
        assert "cov_shrinkage" in est.metadata
        assert "condition_number" in est.metadata

    def test_cov_is_psd(self):
        """La matrice di covarianza deve essere PSD per ogni combinazione."""
        ret = _make_returns()
        for cm in ["sample", "ledoit_wolf", "oas"]:
            est = estimate_parameters(ret, cov_method=cm)
            eigenvalues = np.linalg.eigvalsh(est.cov)
            assert eigenvalues.min() >= -1e-8, (
                f"{cm}: autovalore minimo {eigenvalues.min()}"
            )

    def test_volatilities_helper(self):
        ret = _make_returns(p=3)
        est = estimate_parameters(ret)
        vols = est.volatilities()
        assert vols.shape == (3,)
        assert (vols > 0).all()

    def test_as_of_respects_cutoff(self):
        """estimate_parameters con as_of non deve usare dati futuri."""
        ret = _make_returns(n=500)
        cutoff = date(2022, 6, 1)
        est = estimate_parameters(ret, as_of=cutoff)
        assert est.metadata["date_end"] <= str(cutoff)


class TestValidation:
    def test_bad_shrinkage_detected(self):
        """Shrinkage fuori [0,1] deve essere segnalato."""
        ret = _make_returns()
        mu_est = HistoricalMean().estimate(ret, 252)
        cov_est = SampleCovariance().estimate(ret, 252)

        # Forza un valore illegale per testare
        mu_est.shrinkage_intensity = 1.5
        issues = validate_estimates(mu_est, cov_est)
        assert any("fuori [0,1]" in i for i in issues)
