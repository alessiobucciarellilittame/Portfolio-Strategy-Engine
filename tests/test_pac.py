"""Test per la modalita' PAC — Piano di Accumulo del Capitale."""

import numpy as np
import pandas as pd
import pytest

from src.pac import (
    simulate_pac,
    compute_irr,
    compute_pac_metrics,
    compare_pac_vs_lumpsum,
    _find_contribution_dates,
    PacResult,
    PacComparison,
)
from src.strategies import BuyAndHold, PeriodicRebalance


# ============================================================
# Helpers
# ============================================================

def _make_prices(n_days=504, n_assets=3, seed=42):
    """Genera prezzi sintetici realistici."""
    rng = np.random.RandomState(seed)
    idx = pd.bdate_range("2022-01-03", periods=n_days, name="date")
    daily_mu = np.array([0.0003, 0.0002, 0.0001])[:n_assets]
    daily_std = np.array([0.01, 0.008, 0.005])[:n_assets]
    returns = rng.normal(loc=daily_mu, scale=daily_std, size=(n_days, n_assets))
    prices = 100 * np.cumprod(1 + returns, axis=0)
    tickers = [f"A{i}" for i in range(n_assets)]
    return pd.DataFrame(prices, index=idx, columns=tickers)


def _make_flat_prices(n_days=253, daily_return=0.0004):
    """Prezzi con rendimento giornaliero costante."""
    idx = pd.bdate_range("2022-01-03", periods=n_days, name="date")
    prices_vals = 100 * (1 + daily_return) ** np.arange(n_days)
    return pd.DataFrame({"X": prices_vals}, index=idx)


def _zero_cost_config():
    """Config con costi a zero per test deterministici."""
    return {
        "transaction_costs": {
            "spread_bps": {"equity": 0, "bond": 0, "commodity": 0, "crypto": 0},
            "broker_commission_pct": 0.0,
            "broker_minimum_eur": 0.0,
        }
    }


def _real_cost_config():
    """Config con costi realistici."""
    return {
        "transaction_costs": {
            "spread_bps": {"equity": 5, "bond": 8, "commodity": 10, "crypto": 30},
            "broker_commission_pct": 0.10,
            "broker_minimum_eur": 1.50,
        }
    }


# ============================================================
# Test date versamento
# ============================================================

class TestContributionDates:
    def test_monthly_dates(self):
        prices = _make_prices(n_days=253)
        dates = _find_contribution_dates(prices.index, "monthly")
        # ~12 mesi in un anno
        assert 10 <= len(dates) <= 14

    def test_quarterly_dates(self):
        prices = _make_prices(n_days=504)
        dates = _find_contribution_dates(prices.index, "quarterly")
        # ~8 trimestri in 2 anni
        assert 6 <= len(dates) <= 10

    def test_annual_dates(self):
        prices = _make_prices(n_days=756)
        dates = _find_contribution_dates(prices.index, "annual")
        assert 2 <= len(dates) <= 4

    def test_invalid_frequency(self):
        prices = _make_prices()
        with pytest.raises(ValueError, match="non supportata"):
            _find_contribution_dates(prices.index, "weekly")


# ============================================================
# Test IRR
# ============================================================

class TestIRR:
    def test_irr_zero_return(self):
        """Un investimento che restituisce esattamente il capitale ha IRR ~ 0."""
        from datetime import date
        dates = [date(2022, 1, 1), date(2022, 7, 1), date(2023, 1, 1)]
        amounts = [1000, 1000, 1000]
        # Valore finale = totale versato
        irr = compute_irr(dates, amounts, 3000.0, date(2023, 1, 1))
        assert abs(irr) < 0.02  # Circa zero

    def test_irr_positive_return(self):
        """Guadagno netto -> IRR positivo."""
        from datetime import date
        dates = [date(2022, 1, 1)]
        amounts = [1000]
        # Dopo 1 anno: 1100 (+10%)
        irr = compute_irr(dates, amounts, 1100.0, date(2023, 1, 1))
        assert 0.09 < irr < 0.11  # ~10%

    def test_irr_single_lumpsum(self):
        """IRR di un singolo investimento = CAGR."""
        from datetime import date
        dates = [date(2020, 1, 1)]
        amounts = [10000]
        final = 12000  # +20% su 2 anni
        irr = compute_irr(dates, amounts, final, date(2022, 1, 1))
        expected_cagr = (12000 / 10000) ** 0.5 - 1  # ~9.54%
        assert abs(irr - expected_cagr) < 0.01


# ============================================================
# Test simulate_pac
# ============================================================

class TestSimulatePac:
    def test_total_invested(self):
        """Totale versato = numero versamenti x importo."""
        prices = _make_prices(n_days=253)
        target = {"A0": 0.5, "A1": 0.3, "A2": 0.2}
        result = simulate_pac(
            prices, target, PeriodicRebalance("quarterly"),
            contribution=500, frequency="monthly",
            costs_config=_zero_cost_config(),
        )
        n = result.metrics["n_contributions"]
        expected = n * 500
        assert abs(result.metrics["total_invested"] - expected) < 0.01

    def test_zero_cost_value_consistent(self):
        """Con costi a zero, il valore finale > totale versato (mercato in crescita)."""
        prices = _make_flat_prices(n_days=253, daily_return=0.0004)
        target = {"X": 1.0}
        result = simulate_pac(
            prices, target, BuyAndHold(),
            contribution=1000, frequency="monthly",
            costs_config=_zero_cost_config(),
        )
        # Mercato in crescita -> il valore deve superare il totale versato
        assert result.metrics["final_value"] > result.metrics["total_invested"]
        assert result.metrics["irr"] > 0

    def test_costs_reduce_value(self):
        """I costi reali devono ridurre il valore finale."""
        prices = _make_prices(n_days=253)
        target = {"A0": 0.5, "A1": 0.3, "A2": 0.2}

        r_no_cost = simulate_pac(
            prices, target, BuyAndHold(),
            contribution=1000, frequency="monthly",
            costs_config=_zero_cost_config(),
        )
        r_with_cost = simulate_pac(
            prices, target, BuyAndHold(),
            contribution=1000, frequency="monthly",
            costs_config=_real_cost_config(),
        )
        assert r_with_cost.metrics["final_value"] < r_no_cost.metrics["final_value"]

    def test_small_contributions_high_cost_pct(self):
        """Versamenti piccoli: la commissione minima pesa molto in percentuale."""
        prices = _make_prices(n_days=253)
        target = {"A0": 0.5, "A1": 0.3, "A2": 0.2}

        # Versamento piccolo: 50 EUR, minimo commissione 1.50 EUR per ticker
        r_small = simulate_pac(
            prices, target, BuyAndHold(),
            contribution=50, frequency="monthly",
            costs_config=_real_cost_config(),
        )
        # Versamento grande: 5000 EUR
        r_large = simulate_pac(
            prices, target, BuyAndHold(),
            contribution=5000, frequency="monthly",
            costs_config=_real_cost_config(),
        )
        # Il costo medio in percentuale deve essere piu' alto per versamenti piccoli
        assert r_small.metrics["avg_cost_pct"] > r_large.metrics["avg_cost_pct"]

    def test_single_contribution_like_lumpsum(self):
        """PAC con un solo versamento al giorno zero ~ somma unica (a meno dei costi)."""
        prices = _make_prices(n_days=253)
        target = {"A0": 0.5, "A1": 0.3, "A2": 0.2}

        # PAC: un solo versamento annuale su ~1 anno di dati = 1 versamento
        r_pac = simulate_pac(
            prices, target, BuyAndHold(),
            contribution=10000, frequency="annual",
            costs_config=_zero_cost_config(),
        )
        # Solo 1 versamento
        assert r_pac.metrics["n_contributions"] == 1

    def test_initial_capital(self):
        """Versamento iniziale aggiuntivo."""
        prices = _make_flat_prices(n_days=253, daily_return=0.0004)
        target = {"X": 1.0}
        r = simulate_pac(
            prices, target, BuyAndHold(),
            contribution=500, frequency="monthly",
            initial_capital=5000,
            costs_config=_zero_cost_config(),
        )
        # Il primo versamento include il capitale iniziale
        assert r.cashflows[0].amount >= 5000

    def test_portfolio_value_never_negative(self):
        """Il valore del portafoglio non deve mai essere negativo."""
        prices = _make_prices(n_days=253)
        target = {"A0": 0.5, "A1": 0.3, "A2": 0.2}
        result = simulate_pac(
            prices, target, PeriodicRebalance("quarterly"),
            contribution=500, frequency="monthly",
            costs_config=_real_cost_config(),
        )
        # Dopo il primo versamento, il valore deve essere >= 0
        first_contrib_idx = next(
            i for i, v in enumerate(result.portfolio_value) if v > 0
        )
        assert (result.portfolio_value.iloc[first_contrib_idx:] >= 0).all()

    def test_irr_realistic_range(self):
        """L'IRR deve essere in un range ragionevole."""
        prices = _make_prices(n_days=504)
        target = {"A0": 0.5, "A1": 0.3, "A2": 0.2}
        result = simulate_pac(
            prices, target, PeriodicRebalance("quarterly"),
            contribution=1000, frequency="monthly",
            costs_config=_zero_cost_config(),
        )
        # L'IRR deve essere finito e in un range ragionevole
        assert -0.5 < result.metrics["irr"] < 1.0

    def test_max_drawdown_nonpositive(self):
        """Il max drawdown deve essere <= 0."""
        prices = _make_prices(n_days=504)
        target = {"A0": 0.5, "A1": 0.3, "A2": 0.2}
        result = simulate_pac(
            prices, target, BuyAndHold(),
            contribution=1000, frequency="monthly",
            costs_config=_zero_cost_config(),
        )
        assert result.metrics["max_drawdown"] <= 0


# ============================================================
# Test confronto PAC vs somma unica
# ============================================================

class TestPacVsLumpsum:
    def test_same_total_invested(self):
        """PAC e somma unica devono avere lo stesso totale investito."""
        prices = _make_prices(n_days=253)
        target = {"A0": 0.5, "A1": 0.3, "A2": 0.2}
        comp = compare_pac_vs_lumpsum(
            prices, target, BuyAndHold(),
            contribution=1000, frequency="monthly",
            costs_config=_zero_cost_config(),
        )
        pac_total = comp.summary["pac"]["total_invested"]
        ls_total = comp.summary["lumpsum"]["total_invested"]
        assert abs(pac_total - ls_total) < 0.01

    def test_comparison_structure(self):
        """Il confronto deve avere tutte le chiavi attese."""
        prices = _make_prices(n_days=253)
        target = {"A0": 0.5, "A1": 0.3, "A2": 0.2}
        comp = compare_pac_vs_lumpsum(
            prices, target, BuyAndHold(),
            contribution=1000, frequency="monthly",
            costs_config=_zero_cost_config(),
        )
        assert isinstance(comp, PacComparison)
        assert "pac" in comp.summary
        assert "lumpsum" in comp.summary
        assert "final_value" in comp.summary["pac"]
        assert "final_value" in comp.summary["lumpsum"]
        assert comp.total_invested > 0

    def test_lumpsum_higher_in_rising_market(self):
        """In un mercato costantemente in crescita, la somma unica batte il PAC."""
        prices = _make_flat_prices(n_days=253, daily_return=0.0004)
        target = {"X": 1.0}
        comp = compare_pac_vs_lumpsum(
            prices, target, BuyAndHold(),
            contribution=1000, frequency="monthly",
            costs_config=_zero_cost_config(),
        )
        # La somma unica investe tutto subito -> piu' tempo a lavorare
        assert comp.summary["lumpsum"]["final_value"] > comp.summary["pac"]["final_value"]

    def test_same_period(self):
        """Il periodo deve essere lo stesso."""
        prices = _make_prices(n_days=253)
        target = {"A0": 0.5, "A1": 0.3, "A2": 0.2}
        comp = compare_pac_vs_lumpsum(
            prices, target, BuyAndHold(),
            contribution=1000, frequency="monthly",
            costs_config=_zero_cost_config(),
        )
        assert comp.period_start == prices.index[0].date()
        assert comp.period_end == prices.index[-1].date()

    def test_costs_comparison(self):
        """Con costi reali, il PAC ha costi totali > somma unica (piu' operazioni)."""
        prices = _make_prices(n_days=253)
        target = {"A0": 0.5, "A1": 0.3, "A2": 0.2}
        comp = compare_pac_vs_lumpsum(
            prices, target, BuyAndHold(),
            contribution=1000, frequency="monthly",
            costs_config=_real_cost_config(),
        )
        # PAC: tante piccole operazioni con minimo fisso
        # Somma unica: una sola operazione grande
        assert comp.summary["pac"]["total_costs"] > comp.summary["lumpsum"]["total_costs"]
