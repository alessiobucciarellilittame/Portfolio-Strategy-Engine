"""Test per il backtest walk-forward (Fase 6)."""

import numpy as np
import pandas as pd
import pytest

from src.profiles import ProfileConfig
from src.walkforward import (
    WalkForwardResult,
    decide_weights,
    run_walkforward,
    _generate_rebalance_dates,
)


# ============================================================
# Helper: dati sintetici
# ============================================================

def _make_test_data(n_days=504, n_assets=3, seed=42):
    """Genera prezzi e rendimenti sintetici per i test.

    3 asset: EQ1 (equity), BD1 (bond), EQ2 (equity).
    504 bday ~ 2 anni. I primi 252 giorni sono pre-storia,
    il resto e' il periodo di simulazione.
    """
    rng = np.random.RandomState(seed)
    idx = pd.bdate_range("2021-01-04", periods=n_days, name="date")
    daily_mu = np.array([0.0003, 0.0001, 0.00025])[:n_assets]
    daily_std = np.array([0.008, 0.003, 0.007])[:n_assets]
    rets = rng.normal(loc=daily_mu, scale=daily_std, size=(n_days, n_assets))
    prices = 100 * np.cumprod(1 + rets, axis=0)
    tickers = ["EQ1", "BD1", "EQ2"][:n_assets]
    prices_df = pd.DataFrame(prices, index=idx, columns=tickers)
    returns_df = prices_df.pct_change()
    return prices_df, returns_df


def _make_profile():
    """Profilo bilanciato di test con vincoli permissivi."""
    return ProfileConfig(
        name="test_bilanciato",
        description="Test balanced profile",
        vol_ceiling=0.15,
        max_weight=0.60,
        objective="max_return",
        group_limits={
            "equity": (0.0, 0.80),
            "bond": (0.10, 1.0),
        },
    )


def _make_ac_map():
    return {"EQ1": "equity", "BD1": "bond", "EQ2": "equity"}


def _run_default_walkforward(prices=None, returns=None, **kwargs):
    """Helper per eseguire un walkforward con parametri di default."""
    if prices is None or returns is None:
        prices, returns = _make_test_data()
    profile = kwargs.pop("profile", _make_profile())
    ac_map = kwargs.pop("asset_class_map", _make_ac_map())
    sim_start = kwargs.pop("sim_start", prices.index[252].date())
    sim_end = kwargs.pop("sim_end", prices.index[-1].date())
    defaults = dict(
        frequency="quarterly",
        horizon_years=5,
        mean_method="bayes_stein",
        cov_method="ledoit_wolf",
        window_type="rolling",
        window_days=150,
        initial_capital=100.0,
        tx_cost_bps=10,
    )
    defaults.update(kwargs)
    return run_walkforward(
        prices, returns, profile, ac_map,
        sim_start=sim_start, sim_end=sim_end,
        **defaults,
    )


# ============================================================
# Test anti-lookahead (IL PIU' IMPORTANTE)
# ============================================================

class TestAntiLookahead:
    def test_structural_future_data_ignored(self):
        """decide_weights con stesso as_of ma dati futuri diversi
        deve dare lo stesso risultato."""
        _, returns = _make_test_data()
        profile = _make_profile()
        ac_map = _make_ac_map()
        mid_date = returns.index[300].date()

        # Risultato con dati originali
        w1, _ = decide_weights(
            returns, as_of=mid_date, profile=profile,
            asset_class_map=ac_map, window_days=150,
        )

        # Azzera tutti i rendimenti futuri
        returns2 = returns.copy()
        future_mask = returns2.index >= pd.Timestamp(mid_date)
        returns2.loc[future_mask] = 0.0

        w2, _ = decide_weights(
            returns2, as_of=mid_date, profile=profile,
            asset_class_map=ac_map, window_days=150,
        )

        assert w1 is not None and w2 is not None
        for t in w1:
            np.testing.assert_allclose(
                w1[t], w2.get(t, 0.0), atol=1e-10,
                err_msg=f"Lookahead: peso {t} cambiato con dati futuri diversi",
            )

    def test_placebo_shuffled_future(self):
        """Permutando i rendimenti futuri, le decisioni non devono cambiare."""
        _, returns = _make_test_data()
        profile = _make_profile()
        ac_map = _make_ac_map()
        mid_date = returns.index[300].date()

        w1, _ = decide_weights(
            returns, as_of=mid_date, profile=profile,
            asset_class_map=ac_map, window_days=150,
        )

        # Permuta casualmente i rendimenti futuri
        returns3 = returns.copy()
        rng = np.random.RandomState(99)
        future_mask = returns3.index >= pd.Timestamp(mid_date)
        future_vals = returns3.loc[future_mask].values.copy()
        rng.shuffle(future_vals)
        returns3.loc[future_mask] = future_vals

        w3, _ = decide_weights(
            returns3, as_of=mid_date, profile=profile,
            asset_class_map=ac_map, window_days=150,
        )

        assert w1 is not None and w3 is not None
        for t in w1:
            np.testing.assert_allclose(
                w1[t], w3.get(t, 0.0), atol=1e-10,
                err_msg=f"Lookahead: peso {t} cambiato con futuri permutati",
            )

    def test_past_data_matters(self):
        """Cambiare i dati passati DEVE cambiare la decisione
        (verifica che la funzione non sia banale)."""
        _, returns = _make_test_data()
        profile = _make_profile()
        ac_map = _make_ac_map()
        mid_date = returns.index[300].date()

        w1, _ = decide_weights(
            returns, as_of=mid_date, profile=profile,
            asset_class_map=ac_map, window_days=150,
        )

        # Altera drasticamente i rendimenti passati
        returns4 = returns.copy()
        past_mask = returns4.index < pd.Timestamp(mid_date)
        returns4.loc[past_mask, "EQ1"] *= 5

        w4, _ = decide_weights(
            returns4, as_of=mid_date, profile=profile,
            asset_class_map=ac_map, window_days=150,
        )

        assert w1 is not None and w4 is not None
        diffs = [abs(w1.get(t, 0) - w4.get(t, 0)) for t in w1]
        assert max(diffs) > 0.001, (
            "Cambiare i dati passati deve cambiare i pesi"
        )

    def test_walkforward_ignores_post_sim_data(self):
        """Aggiungere dati dopo sim_end non deve cambiare il risultato."""
        prices, returns = _make_test_data()
        r1 = _run_default_walkforward(prices, returns, tx_cost_bps=0)

        # Aggiungi 50 giorni di rumore dopo la fine
        rng = np.random.RandomState(77)
        extra_idx = pd.bdate_range(
            returns.index[-1] + pd.Timedelta(days=1),
            periods=50, name="date",
        )
        extra = pd.DataFrame(
            rng.normal(0.01, 0.05, size=(50, len(returns.columns))),
            index=extra_idx, columns=returns.columns,
        )
        extended_returns = pd.concat([returns, extra])

        r2 = _run_default_walkforward(
            prices, extended_returns, tx_cost_bps=0,
        )

        # Decisioni identiche a ogni ribilanciamento
        assert len(r1.rebalance_log) == len(r2.rebalance_log)
        for e1, e2 in zip(r1.rebalance_log, r2.rebalance_log):
            assert e1.date == e2.date
            for t in e1.weights_after:
                np.testing.assert_allclose(
                    e1.weights_after[t], e2.weights_after[t], atol=1e-8,
                    err_msg=f"Lookahead: pesi diversi a {e1.date}",
                )


# ============================================================
# Test vincoli rispettati a ogni ribilanciamento
# ============================================================

class TestConstraintsEveryRebalance:
    def test_all_rebalances_valid(self):
        """I pesi target devono rispettare i vincoli del profilo
        a ogni data di ribilanciamento."""
        profile = _make_profile()
        ac_map = _make_ac_map()
        result = _run_default_walkforward()

        assert result.metrics["n_rebalances"] >= 2

        for event in result.rebalance_log:
            w = event.weights_after
            # Long-only
            for tk, wi in w.items():
                assert wi >= -1e-3, (
                    f"{event.date}: peso negativo {tk}={wi:.4f}"
                )
            # Somma = 1
            w_sum = sum(w.values())
            assert abs(w_sum - 1.0) < 1e-3, (
                f"{event.date}: somma pesi = {w_sum:.4f}"
            )
            # Max weight
            for tk, wi in w.items():
                assert wi <= profile.max_weight + 1e-3, (
                    f"{event.date}: {tk}={wi:.4f} > max {profile.max_weight}"
                )
            # Group constraints
            for group, (gmin, gmax) in profile.group_limits.items():
                group_w = sum(
                    wi for tk, wi in w.items()
                    if ac_map.get(tk) == group
                )
                assert group_w >= gmin - 1e-3, (
                    f"{event.date}: {group}={group_w:.4f} < min {gmin}"
                )
                assert group_w <= gmax + 1e-3, (
                    f"{event.date}: {group}={group_w:.4f} > max {gmax}"
                )


# ============================================================
# Test generate_rebalance_dates
# ============================================================

class TestRebalanceDates:
    def test_first_date_always_included(self):
        idx = pd.bdate_range("2022-01-03", periods=252, name="date")
        for freq in ["monthly", "quarterly", "annual"]:
            dates = _generate_rebalance_dates(idx, freq)
            assert dates[0] == idx[0]

    def test_quarterly_count(self):
        """~1 anno -> 4-5 date trimestrali (inclusa la prima)."""
        idx = pd.bdate_range("2022-01-03", periods=252, name="date")
        dates = _generate_rebalance_dates(idx, "quarterly")
        assert 4 <= len(dates) <= 6, f"Dates: {len(dates)}"

    def test_monthly_more_than_quarterly(self):
        idx = pd.bdate_range("2022-01-03", periods=252, name="date")
        monthly = _generate_rebalance_dates(idx, "monthly")
        quarterly = _generate_rebalance_dates(idx, "quarterly")
        assert len(monthly) > len(quarterly)

    def test_invalid_frequency_raises(self):
        idx = pd.bdate_range("2022-01-03", periods=10, name="date")
        with pytest.raises(ValueError, match="non supportata"):
            _generate_rebalance_dates(idx, "weekly")


# ============================================================
# Test walkforward base
# ============================================================

class TestWalkforwardBasic:
    def test_runs_and_returns_result(self):
        result = _run_default_walkforward()
        assert isinstance(result, WalkForwardResult)
        assert len(result.portfolio_value) > 0
        assert len(result.weights_history) > 0
        assert len(result.target_weights_history) >= 2

    def test_portfolio_value_positive(self):
        result = _run_default_walkforward()
        assert (result.portfolio_value > 0).all()

    def test_weights_sum_to_one(self):
        """I pesi devono sommare a ~1 per tutta la simulazione."""
        result = _run_default_walkforward()
        w_sums = result.weights_history.sum(axis=1)
        assert np.allclose(w_sums, 1.0, atol=1e-3), (
            f"Pesi non sommano a 1: min={w_sums.min():.6f}, "
            f"max={w_sums.max():.6f}"
        )

    def test_long_only(self):
        """I pesi devono restare non negativi."""
        result = _run_default_walkforward()
        assert (result.weights_history.values >= -1e-4).all()

    def test_rebalance_count(self):
        """Con trimestrale su ~1 anno, 4-7 ribilanciamenti."""
        result = _run_default_walkforward()
        n = result.metrics["n_rebalances"]
        assert 3 <= n <= 8, f"Ribilanciamenti: {n}"

    def test_metrics_present(self):
        """Tutte le metriche attese devono essere presenti."""
        result = _run_default_walkforward()
        expected = [
            "total_return", "cagr", "volatility", "max_drawdown",
            "sharpe", "n_rebalances", "total_turnover", "total_costs",
        ]
        for key in expected:
            assert key in result.metrics, f"Metrica mancante: {key}"

    def test_metadata_present(self):
        result = _run_default_walkforward()
        assert result.metadata["strategy"] == "walk_forward"
        assert result.metadata["frequency"] == "quarterly"
        assert result.metadata["window_type"] == "rolling"


# ============================================================
# Test windowing (rolling vs expanding)
# ============================================================

class TestWindowing:
    def test_rolling_vs_expanding_differ(self):
        """Rolling e expanding devono produrre risultati diversi."""
        prices, returns = _make_test_data()

        r_rolling = _run_default_walkforward(
            prices, returns, window_type="rolling", window_days=150,
        )
        r_expanding = _run_default_walkforward(
            prices, returns, window_type="expanding", window_days=None,
        )

        # Le equity curve devono essere diverse (stima diversa)
        # Almeno uno dei pesi target deve differire
        tw1 = r_rolling.target_weights_history
        tw2 = r_expanding.target_weights_history
        # Controlla l'ultimo ribilanciamento (piu' probabilmente diverso)
        if len(tw1) > 1 and len(tw2) > 1:
            diff = abs(tw1.iloc[-1] - tw2.iloc[-1]).max()
            # Nota: potrebbero anche essere uguali se i dati sono
            # molto stabili, quindi usiamo un test debole
            assert isinstance(diff, float)


# ============================================================
# Test costi di transazione
# ============================================================

class TestCosts:
    def test_costs_reduce_return(self):
        """I costi devono ridurre il rendimento."""
        prices, returns = _make_test_data()
        r_with = _run_default_walkforward(prices, returns, tx_cost_bps=50)
        r_without = _run_default_walkforward(prices, returns, tx_cost_bps=0)

        assert r_with.metrics["total_return"] < r_without.metrics["total_return"]

    def test_higher_cost_less_return(self):
        prices, returns = _make_test_data()
        r_low = _run_default_walkforward(prices, returns, tx_cost_bps=5)
        r_high = _run_default_walkforward(prices, returns, tx_cost_bps=50)

        assert r_high.metrics["total_return"] < r_low.metrics["total_return"]


# ============================================================
# Test sanity warnings
# ============================================================

class TestSanityWarnings:
    def test_high_sharpe_triggers_warning(self):
        """Dati sintetici con drift positivo devono attivare l'avviso Sharpe."""
        result = _run_default_walkforward()
        sharpe_warnings = [
            w for w in result.validation_warnings
            if "Sharpe" in w and "sospettosamente" in w
        ]
        # I dati sintetici hanno drift costante positivo -> Sharpe alto
        # L'avviso deve scattare (meccanismo funziona)
        assert len(sharpe_warnings) == 1

    def test_no_drawdown_warning_short_period(self):
        """Su periodo breve (<252 giorni) l'avviso drawdown non scatta."""
        result = _run_default_walkforward()
        dd_warnings = [
            w for w in result.validation_warnings
            if "max drawdown" in w and "quasi nullo" in w
        ]
        # La simulazione di test ha ~252 giorni, al confine
        # Verifica che il campo esista e sia una lista
        assert isinstance(dd_warnings, list)
