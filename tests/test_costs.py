"""Test per il layer pratici: costi, fiscalita', FX, transizione (Fase 8)."""

import logging
import numpy as np
import pandas as pd
import pytest

from src.costs import (
    load_costs_config,
    DEFAULT_CAPITAL_EUR,
    _safe_cagr,
    # 8.1
    compute_weighted_ter,
    compute_tx_cost_for_trade,
    apply_ter_drag,
    build_cost_breakdown,
    CostBreakdown,
    # 8.2
    _effective_tax_rate,
    compute_capital_gain_tax,
    compute_bollo,
    build_tax_breakdown,
    TaxBreakdown,
    # 8.3
    compute_fx_impact,
    check_universe_fx,
    FxImpact,
    # 8.4
    build_transition_plan,
    TransitionPlan,
    TransitionOrder,
)
from src.strategies import RebalanceEvent
from src.universe import load_universe


# ============================================================
# Helpers
# ============================================================

ANN_FACTOR = 252

def _make_equity_curve(n_days=500, daily_ret=0.0003, seed=42):
    """Equity curve sintetica."""
    rng = np.random.RandomState(seed)
    idx = pd.bdate_range("2020-01-02", periods=n_days)
    returns = rng.normal(daily_ret, 0.008, n_days)
    pv = 100 * np.cumprod(1 + returns)
    return pd.Series(pv, index=idx, name="portfolio_value")


def _make_weights_history(n_days=500, tickers=None):
    """Pesi costanti."""
    if tickers is None:
        tickers = ["SWDA.MI", "IBGS.MI"]
    idx = pd.bdate_range("2020-01-02", periods=n_days)
    w = np.tile([0.6, 0.4], (n_days, 1))
    return pd.DataFrame(w, index=idx, columns=tickers)


def _make_rebalance_log(n_rebalances=4, tickers=None):
    """Log sintetico con n ribilanciamenti."""
    if tickers is None:
        tickers = ["SWDA.MI", "IBGS.MI"]
    idx = pd.bdate_range("2020-01-02", periods=500)
    events = []
    # Primo evento (acquisto iniziale)
    events.append(RebalanceEvent(
        date=idx[0].date(), turnover=1.0, cost=0.01,
        weights_before={t: 0.0 for t in tickers},
        weights_after={"SWDA.MI": 0.6, "IBGS.MI": 0.4},
    ))
    # Ribilanciamenti successivi
    step = 500 // max(n_rebalances, 1)
    for i in range(1, n_rebalances):
        day = min(i * step, 499)
        events.append(RebalanceEvent(
            date=idx[day].date(), turnover=0.04, cost=0.001,
            weights_before={"SWDA.MI": 0.62, "IBGS.MI": 0.38},
            weights_after={"SWDA.MI": 0.6, "IBGS.MI": 0.4},
        ))
    return events


def _ac_map():
    return {
        "SWDA.MI": "equity", "CSSPX.MI": "equity",
        "SXR8.DE": "equity", "EIMI.MI": "equity",
        "IBGS.MI": "bond", "XGLE.MI": "bond", "IEAC.MI": "bond",
        "SGLD.MI": "commodity",
        "BTC-EUR": "crypto",
    }


def _zero_cost_config():
    """Config con tutti i costi a zero."""
    return {
        "transaction_costs": {
            "spread_bps": {"equity": 0, "bond": 0, "commodity": 0, "crypto": 0},
            "broker_commission_pct": 0.0,
            "broker_minimum_eur": 0.0,
        },
        "tax": {
            "capital_gain_rate": 0.0,
            "govt_bond_rate": 0.0,
            "govt_quota_by_class": {"bond": 0.8, "equity": 0.0, "commodity": 0.0, "crypto": 0.0},
            "crypto_rate": 0.0,
            "bollo_rate": 0.0,
            "etf_no_offset": True,
        },
    }


def _zero_tax_config():
    """Config con tasse a zero ma costi normali."""
    cfg = load_costs_config()
    cfg["tax"]["capital_gain_rate"] = 0.0
    cfg["tax"]["govt_bond_rate"] = 0.0
    cfg["tax"]["crypto_rate"] = 0.0
    cfg["tax"]["bollo_rate"] = 0.0
    return cfg


# ============================================================
# 8.1 — Test costi reali
# ============================================================

class TestCostConfig:
    def test_load_config(self):
        """La configurazione costi/tasse deve caricarsi."""
        cfg = load_costs_config()
        assert "transaction_costs" in cfg
        assert "tax" in cfg
        assert "spread_bps" in cfg["transaction_costs"]

    def test_spread_bps_all_classes(self):
        """Ogni classe di asset deve avere uno spread configurato."""
        cfg = load_costs_config()
        spread = cfg["transaction_costs"]["spread_bps"]
        for ac in ["equity", "bond", "commodity", "crypto"]:
            assert ac in spread
            assert spread[ac] >= 0


class TestWeightedTER:
    def test_positive_ter(self):
        """Il TER ponderato deve essere positivo per un portafoglio reale."""
        w = {"SWDA.MI": 0.6, "IBGS.MI": 0.4}
        ter = compute_weighted_ter(w)
        assert ter > 0

    def test_zero_weights_zero_ter(self):
        """Pesi nulli -> TER nullo."""
        w = {"SWDA.MI": 0.0, "IBGS.MI": 0.0}
        ter = compute_weighted_ter(w)
        assert ter == 0.0


class TestTxCosts:
    def test_zero_turnover_zero_cost(self):
        """Nessun scambio -> costi a zero."""
        sp, comm = compute_tx_cost_for_trade({}, 100000, _ac_map())
        assert sp == 0.0
        assert comm == 0.0

    def test_crypto_higher_spread(self):
        """Lo spread crypto deve essere maggiore di quello equity."""
        cfg = load_costs_config()
        trade_eq = {"SWDA.MI": 0.1}
        trade_cr = {"BTC-EUR": 0.1}
        sp_eq, _ = compute_tx_cost_for_trade(trade_eq, 100000, _ac_map(), cfg)
        sp_cr, _ = compute_tx_cost_for_trade(trade_cr, 100000, _ac_map(), cfg)
        assert sp_cr > sp_eq

    def test_broker_minimum(self):
        """La commissione minima broker deve applicarsi per piccoli ordini."""
        cfg = load_costs_config()
        trade = {"SWDA.MI": 0.001}  # Ordine molto piccolo
        _, comm = compute_tx_cost_for_trade(trade, 1000, _ac_map(), cfg)
        assert comm >= cfg["transaction_costs"]["broker_minimum_eur"]


class TestTERDrag:
    def test_ter_reduces_value(self):
        """Il TER drag deve ridurre il valore del portafoglio."""
        pv = _make_equity_curve()
        wh = _make_weights_history()
        pv_net, ter_total = apply_ter_drag(pv, wh)
        assert pv_net.iloc[-1] <= pv.iloc[-1]
        assert ter_total >= 0

    def test_zero_ter_no_drag(self):
        """Con TER a zero, nessun drag."""
        pv = _make_equity_curve()
        # Cripto ha TER=0
        wh = pd.DataFrame(
            np.ones((len(pv), 1)),
            index=pv.index, columns=["BTC-EUR"],
        )
        pv_net, ter_total = apply_ter_drag(pv, wh)
        np.testing.assert_allclose(pv_net.values, pv.values, rtol=1e-10)
        assert abs(ter_total) < 1e-6

    def test_ter_drag_one_year_coherent(self):
        """Il drag su ~1 anno deve essere coerente col TER nominale."""
        # Equity curve piatta (rendimento zero), 1 anno = 252 giorni
        idx = pd.bdate_range("2020-01-02", periods=252)
        pv = pd.Series(100.0 * np.ones(252), index=idx, name="pv")
        wh = pd.DataFrame(
            np.ones((252, 1)),
            index=idx, columns=["SWDA.MI"],
        )
        universe = load_universe()
        ter_annual = universe.loc["SWDA.MI", "ter"] / 100.0  # 0.0020

        pv_net, ter_total = apply_ter_drag(pv, wh, universe)
        actual_drag_pct = 1 - pv_net.iloc[-1] / pv.iloc[-1]

        # Il drag deve essere vicino al TER nominale (entro 10% di tolleranza)
        assert abs(actual_drag_pct - ter_annual) / ter_annual < 0.10


class TestCostBreakdown:
    def test_net_le_gross(self):
        """Il netto costi deve essere <= lordo."""
        pv = _make_equity_curve()
        wh = _make_weights_history()
        log = _make_rebalance_log()
        target = {"SWDA.MI": 0.6, "IBGS.MI": 0.4}
        cb = build_cost_breakdown(pv, wh, log, target, _ac_map())
        assert cb.cagr_net_costs <= cb.cagr_gross

    def test_zero_costs_net_eq_gross(self):
        """Con costi a zero, netto == lordo."""
        pv = _make_equity_curve()
        wh = _make_weights_history()
        log = _make_rebalance_log(n_rebalances=1)
        # Log minimo con zero turnover post-iniziale
        log_zero = [RebalanceEvent(
            date=pv.index[0].date(), turnover=0.0, cost=0.0,
            weights_before={"SWDA.MI": 0.6, "IBGS.MI": 0.4},
            weights_after={"SWDA.MI": 0.6, "IBGS.MI": 0.4},
        )]
        target = {"BTC-EUR": 1.0}  # TER=0
        wh_zero = pd.DataFrame(
            np.ones((len(pv), 1)),
            index=pv.index, columns=["BTC-EUR"],
        )
        cfg = _zero_cost_config()
        cb = build_cost_breakdown(pv, wh_zero, log_zero, target, _ac_map(),
                                  config=cfg)
        np.testing.assert_allclose(cb.cagr_net_costs, cb.cagr_gross, atol=1e-6)
        assert cb.total_costs < 1e-6

    def test_costs_sum(self):
        """Il totale costi deve essere la somma dei singoli componenti."""
        pv = _make_equity_curve()
        wh = _make_weights_history()
        log = _make_rebalance_log()
        target = {"SWDA.MI": 0.6, "IBGS.MI": 0.4}
        cb = build_cost_breakdown(pv, wh, log, target, _ac_map())
        expected_total = cb.ter_drag_total + cb.tx_cost_total
        np.testing.assert_allclose(cb.total_costs, expected_total, rtol=1e-6)


# ============================================================
# 8.2 — Test fiscalita' italiana
# ============================================================

class TestEffectiveTaxRate:
    def test_equity_rate(self):
        """Aliquota equity deve essere 26%."""
        cfg = load_costs_config()
        rate = _effective_tax_rate("equity", cfg)
        assert rate == cfg["tax"]["capital_gain_rate"]

    def test_bond_blended_rate(self):
        """Aliquota bond deve essere mix 12.5%/26%."""
        cfg = load_costs_config()
        rate = _effective_tax_rate("bond", cfg)
        # Con quota govt 80%: 0.80*0.125 + 0.20*0.26 = 0.152
        expected = 0.80 * 0.125 + 0.20 * 0.26
        np.testing.assert_allclose(rate, expected, atol=1e-6)

    def test_crypto_rate(self):
        """Aliquota crypto deve essere il valore configurato."""
        cfg = load_costs_config()
        rate = _effective_tax_rate("crypto", cfg)
        assert rate == cfg["tax"]["crypto_rate"]

    def test_govt_quota_applied(self):
        """L'aliquota agevolata 12.5% deve essere pesata per la quota govt."""
        cfg = load_costs_config()
        # Modifica quota per test
        cfg["tax"]["govt_quota_by_class"]["bond"] = 1.0  # 100% white-list
        rate = _effective_tax_rate("bond", cfg)
        assert rate == cfg["tax"]["govt_bond_rate"]  # 12.5%


class TestBollo:
    def test_bollo_known_value(self):
        """Il bollo su un controvalore noto deve tornare."""
        cfg = load_costs_config()
        # Equity curve nozionale costante a 100, capital_eur = 100_000
        idx = pd.bdate_range("2020-01-02", periods=252)
        pv = pd.Series(100.0 * np.ones(252), index=idx)
        capital = 100_000
        bollo_annual, bollo_total = compute_bollo(pv, cfg, capital_eur=capital)
        expected_annual = capital * cfg["tax"]["bollo_rate"]
        np.testing.assert_allclose(bollo_annual, expected_annual, rtol=1e-3)
        np.testing.assert_allclose(bollo_total, expected_annual, rtol=0.05)

    def test_zero_bollo_rate(self):
        """Aliquota bollo a zero -> nessun bollo."""
        cfg = load_costs_config()
        cfg["tax"]["bollo_rate"] = 0.0
        pv = _make_equity_curve()
        bollo_annual, bollo_total = compute_bollo(pv, cfg)
        assert bollo_annual == 0.0
        assert bollo_total == 0.0


class TestCapitalGainTax:
    def test_zero_rates_no_tax(self):
        """Aliquote a zero -> nessuna imposta."""
        cfg = _zero_tax_config()
        pv = _make_equity_curve(n_days=500, daily_ret=0.001)  # Portafoglio in gain
        log = _make_rebalance_log(n_rebalances=4)
        tax = compute_capital_gain_tax(log, pv, _ac_map(), cfg)
        assert tax == 0.0

    def test_more_rebalances_more_tax(self):
        """Piu' ribilanciamenti -> piu' imposta (a parita' di rendimento lordo)."""
        pv = _make_equity_curve(n_days=500, daily_ret=0.001)
        cfg = load_costs_config()

        log_few = _make_rebalance_log(n_rebalances=2)
        log_many = _make_rebalance_log(n_rebalances=8)

        tax_few = compute_capital_gain_tax(log_few, pv, _ac_map(), cfg)
        tax_many = compute_capital_gain_tax(log_many, pv, _ac_map(), cfg)

        # Il buy&hold (pochi rebalance) paga meno tasse
        assert tax_many >= tax_few

    def test_no_gain_no_tax(self):
        """Portafoglio in perdita -> nessuna imposta."""
        # Equity curve che scende
        idx = pd.bdate_range("2020-01-02", periods=100)
        pv = pd.Series(100 * np.linspace(1.0, 0.8, 100), index=idx)
        log = _make_rebalance_log(n_rebalances=3)
        cfg = load_costs_config()
        tax = compute_capital_gain_tax(log, pv, _ac_map(), cfg)
        assert tax == 0.0


class TestTaxBreakdown:
    def test_zero_tax_no_impact(self):
        """Aliquote a zero -> nessun impatto fiscale."""
        cfg = _zero_tax_config()
        pv = _make_equity_curve()
        log = _make_rebalance_log()
        tb = build_tax_breakdown(pv, log, _ac_map(), config=cfg)
        assert tb.total_tax < 1e-6
        np.testing.assert_allclose(tb.cagr_net_tax, tb.cagr_net_costs, atol=1e-6)

    def test_tax_notes_present(self):
        """Il breakdown fiscale deve contenere le note obbligatorie."""
        pv = _make_equity_curve()
        log = _make_rebalance_log()
        tb = build_tax_breakdown(pv, log, _ac_map())
        assert any("INDICATIVA" in n or "indicativa" in n for n in tb.notes)
        assert any("redditi di capitale" in n for n in tb.notes)

    def test_net_tax_le_net_costs(self):
        """Il CAGR netto tasse deve essere <= netto costi."""
        pv = _make_equity_curve(n_days=500, daily_ret=0.001)
        log = _make_rebalance_log(n_rebalances=4)
        target = {"SWDA.MI": 0.6, "IBGS.MI": 0.4}
        wh = _make_weights_history()
        cb = build_cost_breakdown(pv, wh, log, target, _ac_map())
        tb = build_tax_breakdown(pv, log, _ac_map(), cost_breakdown=cb)
        assert tb.cagr_net_tax <= tb.cagr_net_costs + 1e-6


# ============================================================
# 8.3 — Test gestione cambio (FX)
# ============================================================

class TestFxImpact:
    def test_eur_instrument_zero_fx(self):
        """Uno strumento EUR ha effetto cambio nullo."""
        idx = pd.bdate_range("2020-01-02", periods=100)
        prices = pd.Series(np.linspace(100, 120, 100), index=idx)
        impact = compute_fx_impact(prices, None, None, "SWDA.MI", "EUR")
        assert impact.fx_return == 0.0
        assert impact.currency == "EUR"
        assert "nullo" in impact.note.lower()

    def test_usd_instrument_fx_separated(self):
        """Uno strumento USD deve avere l'effetto cambio separato."""
        idx = pd.bdate_range("2020-01-02", periods=100)
        # Strumento sale del 20% in USD
        prices_local = pd.Series(np.linspace(100, 120, 100), index=idx)
        # EUR/USD: il dollaro si rafforza del 5% (tasso USD/EUR sale)
        fx_rate = pd.Series(np.linspace(0.90, 0.945, 100), index=idx)
        # Prezzo in EUR = prezzo USD * tasso USD/EUR
        prices_eur = prices_local * fx_rate

        impact = compute_fx_impact(prices_eur, prices_local, fx_rate,
                                   "SPY", "USD")
        assert impact.currency == "USD"
        assert abs(impact.instrument_return_local - 0.20) < 0.01
        assert impact.fx_return != 0.0
        assert abs(impact.total_return_eur -
                   ((1 + impact.instrument_return_local) *
                    (1 + impact.fx_return) - 1)) < 0.02
        assert "NON coperto" in impact.note

    def test_universe_all_eur(self):
        """L'universo corrente e' tutto in EUR -> effetto cambio nullo."""
        impacts = check_universe_fx()
        for imp in impacts:
            assert imp.fx_return == 0.0
            assert imp.currency == "EUR"


# ============================================================
# 8.4 — Test integrazione portafoglio esistente
# ============================================================

class TestTransitionPlan:
    def test_same_portfolio_no_orders(self):
        """Se attuale == target, nessun ordine e costo zero."""
        current = {"SWDA.MI": 60000, "IBGS.MI": 40000}
        target = {"SWDA.MI": 0.6, "IBGS.MI": 0.4}
        plan = build_transition_plan(current, target, 100000, _ac_map())
        assert len(plan.orders) == 0
        assert plan.turnover < 1e-6
        assert plan.tx_cost_total < 1e-6
        assert plan.capital_gain_tax == 0.0

    def test_orders_reach_target(self):
        """Gli ordini devono portare ai pesi target."""
        current = {"SWDA.MI": 70000, "IBGS.MI": 30000}
        target = {"SWDA.MI": 0.5, "IBGS.MI": 0.3, "SGLD.MI": 0.2}
        plan = build_transition_plan(current, target, 100000, _ac_map())

        # Verifica pesi risultanti
        for t, w in target.items():
            if w > 1e-8:
                assert t in plan.weights_after
                np.testing.assert_allclose(plan.weights_after[t], w, atol=1e-6)

    def test_no_gain_no_tax(self):
        """Se non si realizzano plusvalenze, tasse a zero."""
        current = {"SWDA.MI": 60000, "IBGS.MI": 40000}
        target = {"SWDA.MI": 0.4, "IBGS.MI": 0.6}
        # Cost basis = valore attuale -> nessun gain
        cost_basis = {"SWDA.MI": 60000, "IBGS.MI": 40000}
        plan = build_transition_plan(current, target, 100000, _ac_map(),
                                     cost_basis=cost_basis)
        assert plan.capital_gain_tax == 0.0

    def test_gain_generates_tax(self):
        """Vendere posizioni in guadagno genera imposta."""
        current = {"SWDA.MI": 80000, "IBGS.MI": 20000}
        target = {"SWDA.MI": 0.4, "IBGS.MI": 0.6}
        # SWDA.MI: carico 50000, valore 80000 -> gain 30000, vendo ~metà
        cost_basis = {"SWDA.MI": 50000, "IBGS.MI": 20000}
        plan = build_transition_plan(current, target, 100000, _ac_map(),
                                     cost_basis=cost_basis)
        assert plan.capital_gain_tax > 0

    def test_turnover_correct(self):
        """Il turnover deve essere la somma dei |delta_w|."""
        current = {"SWDA.MI": 70000, "IBGS.MI": 30000}
        target = {"SWDA.MI": 0.5, "IBGS.MI": 0.5}
        plan = build_transition_plan(current, target, 100000, _ac_map())
        # delta SWDA = 0.5 - 0.7 = -0.2, delta IBGS = 0.5 - 0.3 = 0.2
        expected_turnover = 0.2 + 0.2
        np.testing.assert_allclose(plan.turnover, expected_turnover, atol=1e-6)

    def test_tx_cost_positive(self):
        """Costi di transazione devono essere positivi con turnover > 0."""
        current = {"SWDA.MI": 70000, "IBGS.MI": 30000}
        target = {"SWDA.MI": 0.5, "IBGS.MI": 0.5}
        plan = build_transition_plan(current, target, 100000, _ac_map())
        assert plan.tx_cost_total > 0
        assert plan.spread_cost > 0
        assert plan.commission_cost > 0

    def test_zero_capital(self):
        """Capitale zero -> piano vuoto."""
        plan = build_transition_plan({}, {"SWDA.MI": 1.0}, 0, _ac_map())
        assert len(plan.orders) == 0
        assert plan.total_transition_cost == 0.0

    def test_bond_lower_tax_rate(self):
        """La vendita di bond governativi deve avere aliquota agevolata."""
        # Vendo IBGS.MI (bond govt) con gain
        current = {"IBGS.MI": 100000}
        target = {"SWDA.MI": 1.0}
        cost_basis = {"IBGS.MI": 80000}  # gain = 20000
        cfg = load_costs_config()
        plan = build_transition_plan(current, target, 100000, _ac_map(),
                                     cost_basis=cost_basis, config=cfg)

        # L'imposta sui bond deve usare l'aliquota mista (< 26%)
        bond_rate = _effective_tax_rate("bond", cfg)
        assert bond_rate < cfg["tax"]["capital_gain_rate"]
        # La tassa pagata deve riflettere l'aliquota agevolata
        expected_tax = 20000 * bond_rate
        np.testing.assert_allclose(plan.capital_gain_tax, expected_tax, rtol=0.01)


# ============================================================
# Test scala capitale e guard anti-NaN
# ============================================================

class TestCapitalScale:
    def test_realistic_capital_no_nan(self):
        """Con capital_eur realistico, cagr_net_costs deve essere finito e <= lordo."""
        pv = _make_equity_curve(n_days=1000, daily_ret=0.0003)
        wh = _make_weights_history(n_days=1000)
        log = _make_rebalance_log(n_rebalances=40)
        target = {"SWDA.MI": 0.6, "IBGS.MI": 0.4}
        cb = build_cost_breakdown(pv, wh, log, target, _ac_map(),
                                  capital_eur=100_000)
        assert np.isfinite(cb.cagr_net_costs)
        assert cb.cagr_net_costs <= cb.cagr_gross
        assert not cb.costs_exceed_capital

    def test_many_rebalances_realistic_capital(self):
        """Multi-ribilanciamento mensile con capital_eur=100k -> netto finito."""
        # Simula ~4 anni di ribilanciamento mensile (~48 eventi)
        n_days = 1000
        pv = _make_equity_curve(n_days=n_days, daily_ret=0.0003)
        wh = _make_weights_history(n_days=n_days)
        idx = pv.index
        events = [RebalanceEvent(
            date=idx[0].date(), turnover=1.0, cost=0.0,
            weights_before={"SWDA.MI": 0.0, "IBGS.MI": 0.0},
            weights_after={"SWDA.MI": 0.6, "IBGS.MI": 0.4},
        )]
        # Aggiungi un ribilanciamento ogni ~21 giorni (mensile)
        for d in range(21, n_days, 21):
            events.append(RebalanceEvent(
                date=idx[d].date(), turnover=0.04, cost=0.0,
                weights_before={"SWDA.MI": 0.62, "IBGS.MI": 0.38},
                weights_after={"SWDA.MI": 0.6, "IBGS.MI": 0.4},
            ))
        target = {"SWDA.MI": 0.6, "IBGS.MI": 0.4}
        cb = build_cost_breakdown(pv, wh, events, target, _ac_map(),
                                  capital_eur=100_000)
        assert np.isfinite(cb.cagr_net_costs), f"CAGR netto e' {cb.cagr_net_costs}"
        assert cb.cagr_net_costs <= cb.cagr_gross
        assert not cb.costs_exceed_capital

    def test_default_capital_eur(self):
        """Il default capital_eur deve essere 100_000."""
        assert DEFAULT_CAPITAL_EUR == 100_000


class TestSafeCagrGuard:
    def test_negative_value_returns_minus_one(self):
        """Se il valore netto e' negativo, _safe_cagr restituisce -1.0."""
        result = _safe_cagr(-50.0, 100.0, 252)
        assert result == -1.0
        assert np.isfinite(result)

    def test_zero_value_returns_minus_one(self):
        """Se il valore netto e' zero, _safe_cagr restituisce -1.0."""
        result = _safe_cagr(0.0, 100.0, 252)
        assert result == -1.0

    def test_positive_value_normal_cagr(self):
        """Con valori positivi, _safe_cagr restituisce un CAGR normale."""
        result = _safe_cagr(110.0, 100.0, 252)
        assert np.isfinite(result)
        assert result > 0

    def test_guard_logs_warning(self, caplog):
        """_safe_cagr deve loggare un warning se il valore e' <= 0."""
        with caplog.at_level(logging.WARNING, logger="src.costs"):
            _safe_cagr(-10.0, 100.0, 252)
        assert any("costi superiori al capitale" in r.message for r in caplog.records)

    def test_cost_breakdown_guard_flag(self):
        """Se i costi superano il capitale, costs_exceed_capital=True."""
        pv = _make_equity_curve(n_days=500)
        wh = _make_weights_history(n_days=500)
        # Molti ribilanciamenti con turnover alto su capitale minuscolo
        idx = pv.index
        events = [RebalanceEvent(
            date=idx[0].date(), turnover=1.0, cost=0.0,
            weights_before={"SWDA.MI": 0.0, "IBGS.MI": 0.0},
            weights_after={"SWDA.MI": 0.6, "IBGS.MI": 0.4},
        )]
        for d in range(5, 500, 5):
            events.append(RebalanceEvent(
                date=idx[d].date(), turnover=0.5, cost=0.0,
                weights_before={"SWDA.MI": 0.8, "IBGS.MI": 0.2},
                weights_after={"SWDA.MI": 0.6, "IBGS.MI": 0.4},
            ))
        target = {"SWDA.MI": 0.6, "IBGS.MI": 0.4}
        # Capitale minuscolo: le fee assolute mangiano tutto
        cb = build_cost_breakdown(pv, wh, events, target, _ac_map(),
                                  capital_eur=10)
        # Il CAGR netto NON deve essere NaN
        assert np.isfinite(cb.cagr_net_costs), f"CAGR netto e' {cb.cagr_net_costs}"
        assert cb.costs_exceed_capital
        assert cb.cagr_net_costs == -1.0

    def test_tax_breakdown_no_nan(self):
        """build_tax_breakdown non deve mai restituire NaN."""
        pv = _make_equity_curve(n_days=500)
        log = _make_rebalance_log(n_rebalances=4)
        tb = build_tax_breakdown(pv, log, _ac_map(), capital_eur=100_000)
        assert np.isfinite(tb.cagr_net_tax), f"CAGR netto tasse e' {tb.cagr_net_tax}"
        assert np.isfinite(tb.cagr_gross)
