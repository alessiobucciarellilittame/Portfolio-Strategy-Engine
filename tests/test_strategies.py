"""Test per le strategie nel tempo (Fase 5)."""

import numpy as np
import pandas as pd
import pytest

from src.strategies import (
    BuyAndHold,
    PeriodicRebalance,
    ThresholdRebalance,
    simulate,
    compute_metrics,
    get_strategy,
    _evolve_weights,
    RebalanceEvent,
)


def _make_prices(n_days=504, n_assets=3, seed=42):
    """Genera prezzi sintetici realistici."""
    rng = np.random.RandomState(seed)
    idx = pd.bdate_range("2022-01-03", periods=n_days, name="date")
    # Rendimenti giornalieri con drift
    daily_mu = np.array([0.0003, 0.0002, 0.0001])[:n_assets]
    daily_std = np.array([0.01, 0.008, 0.005])[:n_assets]

    returns = rng.normal(loc=daily_mu, scale=daily_std, size=(n_days, n_assets))
    prices = 100 * np.cumprod(1 + returns, axis=0)

    tickers = [f"A{i}" for i in range(n_assets)]
    return pd.DataFrame(prices, index=idx, columns=tickers)


def _make_flat_prices(n_days=100, daily_return=0.001):
    """Prezzi con rendimento giornaliero costante (per test metriche esatte)."""
    idx = pd.bdate_range("2023-01-02", periods=n_days, name="date")
    prices_vals = 100 * (1 + daily_return) ** np.arange(n_days)
    return pd.DataFrame({"X": prices_vals}, index=idx)


# ============================================================
# Test evoluzione pesi
# ============================================================

class TestEvolveWeights:
    def test_equal_returns_no_change(self):
        """Se tutti gli asset hanno lo stesso rendimento, i pesi non cambiano."""
        w = np.array([0.6, 0.4])
        r = np.array([0.01, 0.01])
        w_new = _evolve_weights(w, r)
        np.testing.assert_allclose(w_new, [0.6, 0.4], atol=1e-10)

    def test_different_returns_shift(self):
        """L'asset con rendimento maggiore deve prendere più peso."""
        w = np.array([0.5, 0.5])
        r = np.array([0.10, 0.0])  # A0 sale 10%, A1 fermo
        w_new = _evolve_weights(w, r)
        assert w_new[0] > 0.5
        assert w_new[1] < 0.5
        np.testing.assert_allclose(w_new.sum(), 1.0, atol=1e-10)


# ============================================================
# Test Buy & Hold
# ============================================================

class TestBuyAndHold:
    def test_no_rebalances(self):
        """Buy & Hold non deve mai ribilanciare."""
        prices = _make_prices(n_days=252)
        target = {"A0": 0.5, "A1": 0.3, "A2": 0.2}
        result = simulate(prices, target, BuyAndHold())

        # Solo l'acquisto iniziale
        assert result.metrics["n_rebalances"] == 1
        assert len(result.rebalance_log) == 1

    def test_weights_drift(self):
        """I pesi devono cambiare nel tempo (non restare al target)."""
        prices = _make_prices(n_days=252)
        target = {"A0": 0.5, "A1": 0.3, "A2": 0.2}
        result = simulate(prices, target, BuyAndHold())

        final_w = result.weights_history.iloc[-1].values
        target_w = np.array([0.5, 0.3, 0.2])
        # Dopo un anno, i pesi devono essere diversi dal target
        assert not np.allclose(final_w, target_w, atol=0.001)

    def test_portfolio_value_positive(self):
        prices = _make_prices()
        target = {"A0": 0.5, "A1": 0.3, "A2": 0.2}
        result = simulate(prices, target, BuyAndHold())
        assert (result.portfolio_value > 0).all()


# ============================================================
# Test Ribilanciamento Periodico
# ============================================================

class TestPeriodicRebalance:
    def test_quarterly_count(self):
        """Trimestrale su 2 anni ≈ 8 ribilanciamenti (+ acquisto iniziale)."""
        prices = _make_prices(n_days=504)
        target = {"A0": 0.5, "A1": 0.3, "A2": 0.2}
        result = simulate(prices, target, PeriodicRebalance("quarterly"))

        n_reb = result.metrics["n_rebalances"]
        # Acquisto iniziale + ~8 trimestrali
        assert 7 <= n_reb <= 11, f"Ribilanciamenti: {n_reb}"

    def test_monthly_more_than_quarterly(self):
        """Mensile deve avere più ribilanciamenti di trimestrale."""
        prices = _make_prices(n_days=504)
        target = {"A0": 0.5, "A1": 0.3, "A2": 0.2}

        r_m = simulate(prices, target, PeriodicRebalance("monthly"))
        r_q = simulate(prices, target, PeriodicRebalance("quarterly"))

        assert r_m.metrics["n_rebalances"] > r_q.metrics["n_rebalances"]

    def test_weights_restored_after_rebalance(self):
        """Dopo un ribilanciamento, i pesi devono tornare al target."""
        prices = _make_prices(n_days=252)
        target = {"A0": 0.5, "A1": 0.3, "A2": 0.2}
        result = simulate(prices, target, PeriodicRebalance("quarterly"))

        # Prendi una data di ribilanciamento (non la prima)
        if len(result.rebalance_log) > 1:
            reb_date = result.rebalance_log[1].date
            reb_idx = result.weights_history.index.get_loc(
                pd.Timestamp(reb_date)
            )
            w_at_reb = result.weights_history.iloc[reb_idx].values
            np.testing.assert_allclose(w_at_reb, [0.5, 0.3, 0.2], atol=1e-3)


# ============================================================
# Test Ribilanciamento a Soglia
# ============================================================

class TestThresholdRebalance:
    def test_no_rebalance_if_within_threshold(self):
        """Se i prezzi si muovono poco, non deve ribilanciare."""
        # Prezzi quasi piatti -> pesi quasi invariati
        n = 100
        idx = pd.bdate_range("2023-01-02", periods=n, name="date")
        prices = pd.DataFrame({
            "A": 100 + np.arange(n) * 0.01,  # Quasi piatto
            "B": 100 + np.arange(n) * 0.01,
        }, index=idx)
        target = {"A": 0.5, "B": 0.5}

        result = simulate(prices, target, ThresholdRebalance(threshold=0.05))
        # Solo l'acquisto iniziale, nessun ribilanciamento aggiuntivo
        assert result.metrics["n_rebalances"] == 1

    def test_rebalance_on_large_drift(self):
        """Se un asset sale molto, deve scattare il ribilanciamento."""
        n = 100
        idx = pd.bdate_range("2023-01-02", periods=n, name="date")
        prices = pd.DataFrame({
            "A": 100 * np.exp(np.linspace(0, 0.5, n)),  # +65%
            "B": np.full(n, 100.0),                      # Piatto
        }, index=idx)
        target = {"A": 0.5, "B": 0.5}

        result = simulate(prices, target, ThresholdRebalance(threshold=0.05))
        # Deve aver ribilanciato almeno una volta (oltre all'acquisto)
        assert result.metrics["n_rebalances"] > 1


# ============================================================
# Test costi di transazione
# ============================================================

class TestTransactionCosts:
    def test_costs_reduce_return(self):
        """I costi devono ridurre il rendimento rispetto a zero costi."""
        prices = _make_prices(n_days=504)
        target = {"A0": 0.5, "A1": 0.3, "A2": 0.2}
        strategy = PeriodicRebalance("quarterly")

        r_with_costs = simulate(prices, target, strategy, tx_cost_bps=50)
        r_no_costs = simulate(prices, target, strategy, tx_cost_bps=0)

        assert r_with_costs.metrics["total_return"] < r_no_costs.metrics["total_return"]

    def test_buy_hold_minimal_costs(self):
        """Buy & Hold deve avere solo il costo iniziale."""
        prices = _make_prices()
        target = {"A0": 0.5, "A1": 0.3, "A2": 0.2}
        result = simulate(prices, target, BuyAndHold(), tx_cost_bps=10)

        # Solo 1 evento (acquisto iniziale)
        assert len(result.rebalance_log) == 1
        # Costo iniziale = 100 * 1.0 * 0.001 = 0.10
        assert abs(result.rebalance_log[0].cost - 0.10) < 0.01

    def test_higher_cost_less_return(self):
        """Costi maggiori devono produrre rendimento minore."""
        prices = _make_prices(n_days=504)
        target = {"A0": 0.5, "A1": 0.3, "A2": 0.2}
        strategy = PeriodicRebalance("monthly")

        r_low = simulate(prices, target, strategy, tx_cost_bps=5)
        r_high = simulate(prices, target, strategy, tx_cost_bps=50)

        assert r_high.metrics["total_return"] < r_low.metrics["total_return"]


# ============================================================
# Test metriche su serie sintetiche note
# ============================================================

class TestMetrics:
    def test_cagr_flat_return(self):
        """CAGR con rendimento giornaliero costante deve dare il valore atteso.

        r_daily = 0.001 -> CAGR ≈ (1.001)^252 - 1 ≈ 28.6%
        """
        prices = _make_flat_prices(n_days=253, daily_return=0.001)
        target = {"X": 1.0}
        result = simulate(prices, target, BuyAndHold(), tx_cost_bps=0)

        expected_cagr = (1.001) ** 252 - 1  # ~0.286
        assert abs(result.metrics["cagr"] - expected_cagr) < 0.01

    def test_max_drawdown_known(self):
        """Test max drawdown su serie con un calo noto."""
        idx = pd.bdate_range("2023-01-02", periods=10, name="date")
        # Serie: 100, 110, 120, 90, 85, 95, 100, 105, 110, 115
        prices = pd.DataFrame(
            {"X": [100, 110, 120, 90, 85, 95, 100, 105, 110, 115]},
            index=idx,
        )
        target = {"X": 1.0}
        result = simulate(prices, target, BuyAndHold(), tx_cost_bps=0)

        # Max drawdown: dal picco 120 al minimo 85 = (85-120)/120 = -29.2%
        # Ma il portafoglio parte da ~100 (non 100 esattamente perché il primo
        # giorno ha rendimento 0), il drawdown è calcolato sulla serie pv
        assert result.metrics["max_drawdown"] < -0.25

    def test_volatility_positive(self):
        prices = _make_prices()
        target = {"A0": 0.5, "A1": 0.3, "A2": 0.2}
        result = simulate(prices, target, BuyAndHold())
        assert result.metrics["volatility"] > 0

    def test_weights_sum_to_one(self):
        """I pesi devono sommare a ~1 per tutta la simulazione."""
        prices = _make_prices(n_days=252)
        target = {"A0": 0.5, "A1": 0.3, "A2": 0.2}
        result = simulate(prices, target, PeriodicRebalance("quarterly"))

        w_sums = result.weights_history.sum(axis=1)
        assert np.allclose(w_sums, 1.0, atol=1e-4), (
            f"Pesi non sommano a 1: min={w_sums.min():.6f}, max={w_sums.max():.6f}"
        )

    def test_long_only_positive_weights(self):
        """I pesi devono restare non negativi per tutta la simulazione."""
        prices = _make_prices(n_days=252)
        target = {"A0": 0.5, "A1": 0.3, "A2": 0.2}
        result = simulate(prices, target, BuyAndHold())

        assert (result.weights_history.values >= -1e-6).all()


# ============================================================
# Test registry
# ============================================================

class TestRegistry:
    def test_all_strategies(self):
        for name in ["buy_and_hold", "periodic", "threshold"]:
            s = get_strategy(name)
            assert s.name == name or s.name in ("buy_and_hold", "periodic", "threshold")

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="non trovata"):
            get_strategy("nonexistent")

    def test_periodic_with_params(self):
        s = get_strategy("periodic", frequency="monthly")
        assert s.params["frequency"] == "monthly"
