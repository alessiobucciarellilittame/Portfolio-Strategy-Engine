"""Test per la reportistica (Fase 7)."""

import numpy as np
import pandas as pd
import pytest
from pathlib import Path

from src.estimation import ParameterEstimate
from src.profiles import (
    ProfileConfig,
    ProfileResult,
    build_portfolio_for_profile,
    build_all_profiles,
    load_profiles,
    PROFILE_ORDER,
)
from src.core_satellite import CoreSatelliteResult, build_core_satellite
from src.strategies import StrategyResult, RebalanceEvent, simulate, BuyAndHold
from src.reporting import (
    StrategyReport,
    ComparisonReport,
    InstrumentAllocation,
    build_report,
    build_comparison,
    validate_report,
    render_pdf,
    render_comparison_pdf,
    _check_weasyprint,
    _render_profile_html,
    _render_comparison_html,
)


# ============================================================
# Helper: dati sintetici
# ============================================================

def _make_params(p=9, seed=42):
    """ParameterEstimate realistico con 4 equity, 3 bond, 1 commodity, 1 crypto."""
    tickers = [
        "SWDA.MI", "CSSPX.MI", "SXR8.DE", "EIMI.MI",
        "IBGS.MI", "XGLE.MI", "IEAC.MI", "SGLD.MI",
        "BTC-EUR",
    ][:p]
    mu = np.array([0.08, 0.10, 0.09, 0.06, 0.03, 0.04, 0.05, 0.12, 0.40])[:p]
    vols = np.array([0.12, 0.13, 0.12, 0.14, 0.02, 0.06, 0.04, 0.13, 0.50])[:p]
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


def _asset_class_map():
    return {
        "SWDA.MI": "equity", "CSSPX.MI": "equity",
        "SXR8.DE": "equity", "EIMI.MI": "equity",
        "IBGS.MI": "bond", "XGLE.MI": "bond", "IEAC.MI": "bond",
        "SGLD.MI": "commodity",
        "BTC-EUR": "crypto",
    }


def _make_backtest_result(n_days=500, seed=42):
    """StrategyResult sintetico per i test."""
    rng = np.random.RandomState(seed)
    idx = pd.bdate_range("2020-01-02", periods=n_days, name="date")
    daily_rets = rng.normal(0.0003, 0.008, n_days)
    pv_values = 100 * np.cumprod(1 + daily_rets)
    pv = pd.Series(pv_values, index=idx, name="portfolio_value")

    wh = pd.DataFrame(
        np.tile([0.6, 0.4], (n_days, 1)),
        index=idx, columns=["SWDA.MI", "IBGS.MI"],
    )

    events = [
        RebalanceEvent(
            date=idx[0].date(), turnover=1.0, cost=0.01,
            weights_before={"SWDA.MI": 0.0, "IBGS.MI": 0.0},
            weights_after={"SWDA.MI": 0.6, "IBGS.MI": 0.4},
        )
    ]

    from src.strategies import compute_metrics
    metrics = compute_metrics(pv, events)

    return StrategyResult(
        portfolio_value=pv,
        weights_history=wh,
        metrics=metrics,
        rebalance_log=events,
        metadata={"strategy": "buy_and_hold"},
    )


# ============================================================
# Test costruzione StrategyReport
# ============================================================

class TestBuildReport:
    def test_from_profile_result(self):
        """build_report deve produrre un StrategyReport valido."""
        params = _make_params()
        ac = _asset_class_map()
        profiles = load_profiles()
        pr = build_portfolio_for_profile(
            profiles["bilanciato"], params, horizon_years=5, asset_class_map=ac,
        )
        report = build_report(pr)

        assert isinstance(report, StrategyReport)
        assert report.profile_name == "bilanciato"
        assert report.is_feasible
        assert len(report.allocation) > 0
        assert len(report.disclaimers) > 0

    def test_weights_match_source(self):
        """I pesi nel report devono coincidere con quelli del ProfileResult."""
        params = _make_params()
        ac = _asset_class_map()
        profiles = load_profiles()
        pr = build_portfolio_for_profile(
            profiles["moderato"], params, horizon_years=5, asset_class_map=ac,
        )
        report = build_report(pr)

        # Ricostruisci i pesi dal report
        report_weights = {a.ticker: a.weight for a in report.allocation}
        for t, w in pr.portfolio.weights.items():
            if abs(w) >= 1e-6:
                assert t in report_weights, f"Ticker {t} mancante nel report"
                np.testing.assert_allclose(
                    report_weights[t], w, atol=1e-6,
                    err_msg=f"Peso di {t} diverso nel report",
                )

    def test_stats_match_source(self):
        """Le statistiche nel report devono coincidere con quelle del motore."""
        params = _make_params()
        ac = _asset_class_map()
        profiles = load_profiles()
        pr = build_portfolio_for_profile(
            profiles["bilanciato"], params, horizon_years=5, asset_class_map=ac,
        )
        report = build_report(pr)
        stats = pr.portfolio.stats

        np.testing.assert_allclose(
            report.expected_return, stats["expected_return"], atol=1e-6)
        np.testing.assert_allclose(
            report.expected_volatility, stats["volatility"], atol=1e-6)
        np.testing.assert_allclose(
            report.expected_sharpe, stats["sharpe_ratio"], atol=1e-6)

    def test_with_backtest(self):
        """build_report con backtest deve includere le metriche."""
        params = _make_params()
        ac = _asset_class_map()
        profiles = load_profiles()
        pr = build_portfolio_for_profile(
            profiles["bilanciato"], params, horizon_years=5, asset_class_map=ac,
        )
        bt = _make_backtest_result()
        report = build_report(pr, backtest_result=bt)

        assert report.backtest_cagr is not None
        assert report.backtest_max_drawdown is not None
        assert report.equity_curve is not None
        np.testing.assert_allclose(
            report.backtest_cagr, bt.metrics["cagr"], atol=1e-6)

    def test_with_core_satellite(self):
        """build_report con core_satellite deve usare i pesi combinati."""
        params = _make_params()
        ac = _asset_class_map()
        profiles = load_profiles()
        cs = build_core_satellite(
            profiles["bilanciato"], params, ac,
            crypto_weight=0.05, horizon_years=5,
        )
        pr = cs.profile_result
        report = build_report(pr, core_satellite_result=cs)

        assert report.satellite_weight == cs.crypto_weight_actual
        # Il report deve contenere il satellite
        sat_tickers = [a.ticker for a in report.allocation if a.is_satellite]
        assert len(sat_tickers) > 0

        # Stats dal combined
        np.testing.assert_allclose(
            report.expected_return, cs.combined_stats["expected_return"], atol=1e-6)

    def test_instrument_metadata(self):
        """Le allocazioni devono avere i metadati corretti dall'universo."""
        params = _make_params()
        ac = _asset_class_map()
        profiles = load_profiles()
        pr = build_portfolio_for_profile(
            profiles["bilanciato"], params, horizon_years=5, asset_class_map=ac,
        )
        report = build_report(pr)

        for a in report.allocation:
            assert a.name != "", f"Nome mancante per {a.ticker}"
            assert a.asset_class != "sconosciuto", f"Classe mancante per {a.ticker}"
            assert a.ter >= 0


# ============================================================
# Test validazione report
# ============================================================

class TestValidateReport:
    def test_valid_report_passes(self):
        """Un report valido non deve avere problemi."""
        params = _make_params()
        ac = _asset_class_map()
        profiles = load_profiles()
        pr = build_portfolio_for_profile(
            profiles["bilanciato"], params, horizon_years=5, asset_class_map=ac,
        )
        report = build_report(pr)
        issues = validate_report(report)
        assert len(issues) == 0, f"Problemi: {issues}"

    def test_weights_sum_to_one(self):
        """I pesi nel report devono sommare a 1."""
        params = _make_params()
        ac = _asset_class_map()
        profiles = load_profiles()
        pr = build_portfolio_for_profile(
            profiles["dinamico"], params, horizon_years=5, asset_class_map=ac,
        )
        report = build_report(pr)
        total = sum(a.weight for a in report.allocation)
        assert abs(total - 1.0) < 1e-3, f"Pesi sommano a {total}"

    def test_class_allocation_consistent(self):
        """L'allocazione per classe deve essere coerente con quella per strumento."""
        params = _make_params()
        ac = _asset_class_map()
        profiles = load_profiles()
        pr = build_portfolio_for_profile(
            profiles["bilanciato"], params, horizon_years=5, asset_class_map=ac,
        )
        report = build_report(pr)

        class_check: dict[str, float] = {}
        for a in report.allocation:
            class_check[a.asset_class] = class_check.get(a.asset_class, 0.0) + a.weight

        for cls, w in class_check.items():
            np.testing.assert_allclose(
                w, report.class_allocation[cls], atol=1e-4,
                err_msg=f"Classe '{cls}' incoerente",
            )

    def test_all_profiles_valid(self):
        """Tutti i profili devono produrre report validi."""
        params = _make_params()
        ac = _asset_class_map()
        results = build_all_profiles(params, horizon_years=5, asset_class_map=ac)
        for pr in results:
            report = build_report(pr)
            issues = validate_report(report)
            assert len(issues) == 0, (
                f"Profilo '{report.profile_name}': {issues}"
            )


# ============================================================
# Test confronto multi-profilo
# ============================================================

class TestComparison:
    def test_build_comparison(self):
        """build_comparison deve raccogliere tutti i profili."""
        params = _make_params()
        ac = _asset_class_map()
        results = build_all_profiles(params, horizon_years=5, asset_class_map=ac)
        reports = [build_report(pr) for pr in results]
        comp = build_comparison(reports)

        assert isinstance(comp, ComparisonReport)
        assert len(comp.profiles) == 5

    def test_comparison_with_equity_curves(self):
        """Il confronto con equity curves deve funzionare."""
        params = _make_params()
        ac = _asset_class_map()
        results = build_all_profiles(params, horizon_years=5, asset_class_map=ac)
        bt = _make_backtest_result()
        reports = [build_report(pr, backtest_result=bt) for pr in results]
        comp = build_comparison(reports)

        assert len(comp.equity_curves) == 5


# ============================================================
# Test rendering HTML
# ============================================================

class TestRendering:
    def test_html_generation(self):
        """La generazione HTML deve produrre un documento valido."""
        params = _make_params()
        ac = _asset_class_map()
        profiles = load_profiles()
        pr = build_portfolio_for_profile(
            profiles["bilanciato"], params, horizon_years=5, asset_class_map=ac,
        )
        report = build_report(pr)
        html = _render_profile_html(report)

        assert "<!DOCTYPE html>" in html
        assert "bilanciato" in html.lower() or "Bilanciato" in html
        assert "Allocazione" in html
        assert "Avvertenze" in html

    def test_comparison_html_generation(self):
        """La generazione HTML confronto deve includere tutti i profili."""
        params = _make_params()
        ac = _asset_class_map()
        results = build_all_profiles(params, horizon_years=5, asset_class_map=ac)
        reports = [build_report(pr) for pr in results]
        comp = build_comparison(reports)
        html = _render_comparison_html(comp)

        assert "<!DOCTYPE html>" in html
        for name in PROFILE_ORDER:
            assert name.capitalize() in html

    def test_html_with_backtest(self):
        """HTML con backtest deve includere metriche e non sollevare eccezioni."""
        params = _make_params()
        ac = _asset_class_map()
        profiles = load_profiles()
        pr = build_portfolio_for_profile(
            profiles["bilanciato"], params, horizon_years=5, asset_class_map=ac,
        )
        bt = _make_backtest_result()
        report = build_report(pr, backtest_result=bt)

        # Deve avere le metriche valorizzate
        assert report.backtest_cagr is not None
        assert report.backtest_sharpe is not None
        assert report.backtest_max_drawdown is not None

        html = _render_profile_html(report)

        assert "<!DOCTYPE html>" in html
        assert "backtest" in html.lower()
        assert "CAGR" in html
        # Valori numerici formattati devono comparire
        assert f"{report.backtest_cagr:.2%}" in html
        assert f"{report.backtest_max_drawdown:.2%}" in html

    def test_html_with_satellite(self):
        """HTML con satellite cripto deve mostrare la sezione satellite."""
        params = _make_params()
        ac = _asset_class_map()
        profiles = load_profiles()
        cs = build_core_satellite(
            profiles["bilanciato"], params, ac,
            crypto_weight=0.05, horizon_years=5,
        )
        pr = cs.profile_result
        report = build_report(pr, core_satellite_result=cs)

        html = _render_profile_html(report)

        assert "<!DOCTYPE html>" in html
        assert report.satellite_weight > 0
        # Deve contenere almeno un ticker satellite
        sat_tickers = [a.ticker for a in report.allocation if a.is_satellite]
        assert len(sat_tickers) > 0
        for t in sat_tickers:
            assert t in html

    def test_html_with_backtest_and_satellite(self):
        """HTML con backtest + satellite: caso completo, nessuna eccezione."""
        params = _make_params()
        ac = _asset_class_map()
        profiles = load_profiles()
        cs = build_core_satellite(
            profiles["bilanciato"], params, ac,
            crypto_weight=0.05, horizon_years=5,
        )
        pr = cs.profile_result
        bt = _make_backtest_result()
        report = build_report(pr, backtest_result=bt, core_satellite_result=cs)

        html = _render_profile_html(report)

        assert "<!DOCTYPE html>" in html
        assert "backtest" in html.lower()
        assert f"{report.backtest_cagr:.2%}" in html

    def test_html_without_backtest_no_section(self):
        """HTML senza backtest non deve contenere la sezione backtest."""
        params = _make_params()
        ac = _asset_class_map()
        profiles = load_profiles()
        pr = build_portfolio_for_profile(
            profiles["bilanciato"], params, horizon_years=5, asset_class_map=ac,
        )
        report = build_report(pr)
        assert report.backtest_cagr is None

        html = _render_profile_html(report)

        assert "<!DOCTYPE html>" in html
        assert "CAGR" not in html


# ============================================================
# Test generazione PDF
# ============================================================

class TestPDF:
    @pytest.mark.skipif(not _check_weasyprint(), reason="weasyprint non disponibile")
    def test_pdf_created(self, tmp_path):
        """Il PDF deve essere creato e non vuoto."""
        params = _make_params()
        ac = _asset_class_map()
        profiles = load_profiles()
        pr = build_portfolio_for_profile(
            profiles["bilanciato"], params, horizon_years=5, asset_class_map=ac,
        )
        report = build_report(pr)
        pdf_path = render_pdf(report, output_path=tmp_path / "test_piano.pdf")

        assert pdf_path.exists()
        assert pdf_path.stat().st_size > 0

    @pytest.mark.skipif(not _check_weasyprint(), reason="weasyprint non disponibile")
    def test_pdf_with_backtest(self, tmp_path):
        """Il PDF con backtest deve includere la equity curve."""
        params = _make_params()
        ac = _asset_class_map()
        profiles = load_profiles()
        pr = build_portfolio_for_profile(
            profiles["bilanciato"], params, horizon_years=5, asset_class_map=ac,
        )
        bt = _make_backtest_result()
        report = build_report(pr, backtest_result=bt)
        pdf_path = render_pdf(report, output_path=tmp_path / "test_bt.pdf")

        assert pdf_path.exists()
        assert pdf_path.stat().st_size > 1000  # Deve avere i grafici

    @pytest.mark.skipif(not _check_weasyprint(), reason="weasyprint non disponibile")
    def test_comparison_pdf_created(self, tmp_path):
        """Il PDF di confronto deve essere creato."""
        params = _make_params()
        ac = _asset_class_map()
        results = build_all_profiles(params, horizon_years=5, asset_class_map=ac)
        reports = [build_report(pr) for pr in results]
        comp = build_comparison(reports)
        pdf_path = render_comparison_pdf(comp, output_path=tmp_path / "test_confronto.pdf")

        assert pdf_path.exists()
        assert pdf_path.stat().st_size > 0

    def test_no_weasyprint_message(self):
        """Senza weasyprint, il messaggio di errore deve essere chiaro."""
        # Non possiamo realmente testare l'assenza di weasyprint se e' installato,
        # ma possiamo verificare che _check_weasyprint restituisca un booleano.
        result = _check_weasyprint()
        assert isinstance(result, bool)
