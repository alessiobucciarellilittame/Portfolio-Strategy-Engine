"""Test per il modulo Black-Litterman."""

import numpy as np
import pandas as pd
import pytest

from src.black_litterman import (
    BLConfig,
    BLResult,
    build_equilibrium_weights,
    calibrate_delta,
    compute_implied_returns,
    compute_posterior,
    idzorek_omega,
    load_bl_config,
    parse_views,
    run_black_litterman,
    validate_view,
    validate_views,
    _normalize_view,
)
from src.estimation import estimate_parameters, ParameterEstimate
from src.optimizer import get_objective, PortfolioResult
from src.constraints import PortfolioConstraints
from src.profiles import (
    load_profiles,
    build_portfolio_for_profile,
    build_all_profiles,
    PROFILE_ORDER,
)
from src.universe import load_universe


# ============================================================
# Fixtures
# ============================================================

CORE_TICKERS = [
    "SWDA.MI", "CSSPX.MI", "SXR8.DE", "EIMI.MI",
    "IBGS.MI", "XGLE.MI", "IEAC.MI",
    "SGLD.MI",
]

AC_MAP = {
    "SWDA.MI": "equity", "CSSPX.MI": "equity", "SXR8.DE": "equity",
    "EIMI.MI": "equity", "IBGS.MI": "bond", "XGLE.MI": "bond",
    "IEAC.MI": "bond", "SGLD.MI": "commodity", "BTC-EUR": "crypto",
}


def _make_cov(tickers=None, seed=42):
    """Genera una matrice di covarianza realistica per i test."""
    if tickers is None:
        tickers = CORE_TICKERS
    n = len(tickers)
    rng = np.random.RandomState(seed)

    # Volatilità realistiche annuali
    vols_map = {
        "SWDA.MI": 0.14, "CSSPX.MI": 0.15, "SXR8.DE": 0.16,
        "EIMI.MI": 0.18, "IBGS.MI": 0.02, "XGLE.MI": 0.06,
        "IEAC.MI": 0.04, "SGLD.MI": 0.14,
    }
    vols = np.array([vols_map.get(t, 0.10) for t in tickers])

    # Correlazioni realistiche
    corr = np.eye(n)
    for i in range(n):
        for j in range(i + 1, n):
            ac_i = AC_MAP.get(tickers[i], "other")
            ac_j = AC_MAP.get(tickers[j], "other")
            if ac_i == ac_j == "equity":
                c = 0.75 + rng.uniform(-0.05, 0.05)
            elif ac_i == ac_j == "bond":
                c = 0.60 + rng.uniform(-0.05, 0.05)
            elif (ac_i == "equity" and ac_j == "bond") or (ac_i == "bond" and ac_j == "equity"):
                c = 0.20 + rng.uniform(-0.05, 0.05)
            else:
                c = 0.10 + rng.uniform(-0.05, 0.05)
            corr[i, j] = corr[j, i] = c

    D = np.diag(vols)
    cov = D @ corr @ D
    # Forza simmetria esatta
    cov = (cov + cov.T) / 2
    return cov


def _make_bl_config(views=None, tau=0.05, mu_target=0.055, delta=None, eq_weights=None):
    """Crea una BLConfig per test."""
    return BLConfig(
        equilibrium_weights=eq_weights or {"equity": 0.60, "bond": 0.35, "commodity": 0.05},
        mu_target=mu_target,
        tau=tau,
        delta=delta,
        views=views or [],
    )


def _make_returns(tickers=None, n=1000, seed=42):
    """Genera rendimenti sintetici realistici per i test di integrazione."""
    if tickers is None:
        tickers = CORE_TICKERS + ["BTC-EUR"]
    rng = np.random.RandomState(seed)

    # Volatilità giornaliere realistiche per asset class
    daily_vols = {
        "SWDA.MI": 0.009, "CSSPX.MI": 0.010, "SXR8.DE": 0.010,
        "EIMI.MI": 0.011, "IBGS.MI": 0.001, "XGLE.MI": 0.003,
        "IEAC.MI": 0.002, "SGLD.MI": 0.008, "BTC-EUR": 0.030,
    }
    daily_means = {
        "SWDA.MI": 0.0003, "CSSPX.MI": 0.0004, "SXR8.DE": 0.0003,
        "EIMI.MI": 0.0002, "IBGS.MI": 0.0001, "XGLE.MI": 0.0001,
        "IEAC.MI": 0.0001, "SGLD.MI": 0.0002, "BTC-EUR": 0.001,
    }

    data = np.column_stack([
        rng.normal(loc=daily_means.get(t, 0.0003), scale=daily_vols.get(t, 0.01), size=n)
        for t in tickers
    ])
    idx = pd.bdate_range("2015-01-02", periods=n, name="date")
    return pd.DataFrame(data, index=idx, columns=tickers)


# ============================================================
# Test 1: Roundtrip di equilibrio
# ============================================================

class TestRoundtrip:
    """Verifica che i rendimenti impliciti, re-ottimizzati, rigenerino w_eq.

    Il roundtrip classico: Pi = delta*Sigma*w_eq (excess returns).
    Se ottimizzi MaxSharpe con mu_total = Pi + rf, il solver computa
    excess = mu - rf = Pi = delta*Sigma*w_eq, la cui soluzione non vincolata
    è w* ∝ Sigma^-1 * Pi = delta * w_eq ∝ w_eq.
    """

    def test_roundtrip_max_sharpe_no_constraints(self):
        """MaxSharpe con mu=mu_bl (=Pi+rf, zero view), senza vincoli -> ~w_eq."""
        cov = _make_cov()
        config = _make_bl_config()
        bl = run_black_litterman(cov, CORE_TICKERS, AC_MAP, config)

        # mu_bl = Pi + rf (rendimenti totali, coerenti col sistema)
        params = ParameterEstimate(
            mu=bl.mu_bl, cov=cov, tickers=CORE_TICKERS,
            metadata={"mean_method": "black_litterman"},
        )

        # Vincoli molto larghi per permettere il roundtrip
        constraints = PortfolioConstraints(
            long_only=True,
            fully_invested=True,
            max_weight=1.0,
        )

        objective = get_objective("max_sharpe")
        result = objective.solve(params, constraints)

        assert result.is_feasible()
        w_opt = np.array([result.weights[t] for t in CORE_TICKERS])

        # Con vincoli minimali, la soluzione deve essere vicina a w_eq
        np.testing.assert_allclose(w_opt, bl.w_eq, atol=0.02)

    def test_roundtrip_max_return_with_vol_ceiling(self):
        """MaxReturn con vol ceiling = vol_eq + epsilon -> pesi ~w_eq."""
        cov = _make_cov()
        config = _make_bl_config()
        bl = run_black_litterman(cov, CORE_TICKERS, AC_MAP, config)

        vol_eq = float(np.sqrt(bl.w_eq @ cov @ bl.w_eq))

        params = ParameterEstimate(
            mu=bl.mu_bl, cov=cov, tickers=CORE_TICKERS,
            metadata={"mean_method": "black_litterman"},
        )

        constraints = PortfolioConstraints(
            long_only=True,
            fully_invested=True,
            max_weight=1.0,
            risk_ceiling=vol_eq + 0.001,
        )

        objective = get_objective("max_return")
        result = objective.solve(params, constraints)
        assert result.is_feasible()

        w_opt = np.array([result.weights[t] for t in CORE_TICKERS])
        # max_return at the vol boundary: less tight match
        np.testing.assert_allclose(w_opt, bl.w_eq, atol=0.05)


# ============================================================
# Test 2: Nessuna view => mu_BL == Pi
# ============================================================

class TestNoViews:
    """Senza view, mu_BL deve essere Pi + rf."""

    def test_no_views_mu_equals_pi_plus_rf(self):
        cov = _make_cov()
        config = _make_bl_config(views=[])
        bl = run_black_litterman(cov, CORE_TICKERS, AC_MAP, config)

        from src.config import get_risk_free_rate
        rf = get_risk_free_rate()
        np.testing.assert_allclose(bl.mu_bl, bl.pi + rf, atol=1e-12)

    def test_no_views_posterior_cov_is_none(self):
        cov = _make_cov()
        config = _make_bl_config(views=[])
        bl = run_black_litterman(cov, CORE_TICKERS, AC_MAP, config)
        assert bl.posterior_cov is None
        assert bl.views_P is None
        assert bl.views_Q is None
        assert bl.omega is None


# ============================================================
# Test 3: View assoluta - confidenza alta vs bassa
# ============================================================

class TestAbsoluteView:
    """View assoluta: confidenza alta sposta mu_BL verso la view."""

    def test_high_confidence_moves_to_view(self):
        """Con confidenza ~100%, mu_BL[X] ≈ valore della view."""
        cov = _make_cov()
        view_value = 0.12  # Aspetto 12% da CSSPX.MI

        config = _make_bl_config(views=[{
            "type": "absolute",
            "assets": ["CSSPX.MI"],
            "value": view_value,
            "confidence": 99,
        }])

        bl = run_black_litterman(cov, CORE_TICKERS, AC_MAP, config)
        idx = CORE_TICKERS.index("CSSPX.MI")

        # Con confidenza 99%, mu_BL dovrebbe essere molto vicino alla view
        assert abs(bl.mu_bl[idx] - view_value) < 0.01

    def test_low_confidence_stays_near_pi(self):
        """Con confidenza bassa, mu_BL ≈ Pi + rf (equilibrio senza view)."""
        cov = _make_cov()
        view_value = 0.12

        config = _make_bl_config(views=[{
            "type": "absolute",
            "assets": ["CSSPX.MI"],
            "value": view_value,
            "confidence": 1,  # quasi zero
        }])

        bl = run_black_litterman(cov, CORE_TICKERS, AC_MAP, config)

        # Con confidenza 1%, mu_BL dovrebbe essere quasi invariato
        bl_no_views = run_black_litterman(cov, CORE_TICKERS, AC_MAP, _make_bl_config())
        np.testing.assert_allclose(bl.mu_bl, bl_no_views.mu_bl, atol=0.005)

    def test_monotonicity_with_confidence(self):
        """Alzando la confidenza, mu_BL[X] si muove monotonicamente verso la view."""
        cov = _make_cov()
        view_value = 0.15
        idx = CORE_TICKERS.index("CSSPX.MI")

        prev_distance = float("inf")
        for conf in [10, 30, 50, 70, 90, 99]:
            config = _make_bl_config(views=[{
                "type": "absolute",
                "assets": ["CSSPX.MI"],
                "value": view_value,
                "confidence": conf,
            }])
            bl = run_black_litterman(cov, CORE_TICKERS, AC_MAP, config)
            distance = abs(bl.mu_bl[idx] - view_value)
            assert distance <= prev_distance + 1e-10
            prev_distance = distance


# ============================================================
# Test 4: View relativa
# ============================================================

class TestRelativeView:
    """View relativa: differenziale si sposta nella direzione attesa."""

    def test_relative_view_increases_spread(self):
        """X batte Y di z% => mu_BL[X] - mu_BL[Y] si muove verso z%."""
        cov = _make_cov()
        spread_view = 0.03  # 3% annuo

        config_no_view = _make_bl_config()
        bl_base = run_black_litterman(cov, CORE_TICKERS, AC_MAP, config_no_view)

        config_view = _make_bl_config(views=[{
            "type": "relative",
            "long_assets": ["CSSPX.MI"],
            "short_assets": ["SXR8.DE"],
            "value": spread_view,
            "confidence": 70,
        }])
        bl_view = run_black_litterman(cov, CORE_TICKERS, AC_MAP, config_view)

        idx_long = CORE_TICKERS.index("CSSPX.MI")
        idx_short = CORE_TICKERS.index("SXR8.DE")

        spread_base = bl_base.pi[idx_long] - bl_base.pi[idx_short]
        spread_post = bl_view.mu_bl[idx_long] - bl_view.mu_bl[idx_short]

        # Lo spread post deve muoversi verso la view (spread_view > 0)
        assert spread_post > spread_base

    def test_relative_view_monotonicity(self):
        """Alzando confidenza, lo spread converge verso il valore della view."""
        cov = _make_cov()
        spread_view = 0.04
        idx_long = CORE_TICKERS.index("CSSPX.MI")
        idx_short = CORE_TICKERS.index("SXR8.DE")

        prev_spread = None
        for conf in [10, 30, 50, 70, 90]:
            config = _make_bl_config(views=[{
                "type": "relative",
                "long_assets": ["CSSPX.MI"],
                "short_assets": ["SXR8.DE"],
                "value": spread_view,
                "confidence": conf,
            }])
            bl = run_black_litterman(cov, CORE_TICKERS, AC_MAP, config)
            spread = bl.mu_bl[idx_long] - bl.mu_bl[idx_short]

            if prev_spread is not None:
                # Lo spread deve crescere monotonicamente con la confidenza
                assert spread >= prev_spread - 1e-10
            prev_spread = spread


# ============================================================
# Test 5: mu_BL finito e Sigma invariata
# ============================================================

class TestNumericalStability:
    """Verifica stabilità numerica: mu finito, Sigma invariata."""

    def test_mu_bl_always_finite(self):
        """mu_BL deve essere finito per qualsiasi configurazione."""
        cov = _make_cov()

        configs = [
            _make_bl_config(),
            _make_bl_config(views=[{
                "type": "absolute", "assets": ["CSSPX.MI"],
                "value": 0.30, "confidence": 99,
            }]),
            _make_bl_config(views=[{
                "type": "relative", "long_assets": ["SWDA.MI"],
                "short_assets": ["IBGS.MI"], "value": 0.10, "confidence": 50,
            }]),
        ]

        for config in configs:
            bl = run_black_litterman(cov, CORE_TICKERS, AC_MAP, config)
            assert np.all(np.isfinite(bl.mu_bl))
            # Controllo range sensato (annualizzati)
            assert np.all(bl.mu_bl > -0.50)
            assert np.all(bl.mu_bl < 1.00)

    def test_cov_not_modified_by_bl(self):
        """La covarianza passata all'ottimizzatore resta invariata."""
        cov_original = _make_cov()
        cov_input = cov_original.copy()

        config = _make_bl_config(views=[{
            "type": "absolute", "assets": ["CSSPX.MI"],
            "value": 0.12, "confidence": 80,
        }])

        bl = run_black_litterman(cov_input, CORE_TICKERS, AC_MAP, config)
        # cov_input non deve essere stato modificato
        np.testing.assert_array_equal(cov_input, cov_original)

    def test_w_eq_sums_to_one(self):
        """Pesi di equilibrio normalizzati devono sommare a 1."""
        cov = _make_cov()
        config = _make_bl_config()
        bl = run_black_litterman(cov, CORE_TICKERS, AC_MAP, config)
        assert abs(bl.w_eq.sum() - 1.0) < 1e-10
        assert np.all(bl.w_eq >= 0)


# ============================================================
# Test 6: Esclusione cripto
# ============================================================

class TestCryptoExclusion:
    """BL opera solo sul core tradizionale, cripto escluse."""

    def test_crypto_not_in_bl_tickers(self):
        """Se passo ticker con crypto, BL li include se li riceve."""
        # In pratica BL riceve solo i ticker core (filter_params prima)
        # Ma verifichiamo che se per errore li includiamo,
        # i pesi crypto nell'equilibrio sono 0 (non c'è classe crypto nei pesi)
        tickers_with_crypto = CORE_TICKERS + ["BTC-EUR"]
        n = len(tickers_with_crypto)
        cov = np.eye(n) * 0.01
        config = _make_bl_config()

        bl = run_black_litterman(cov, tickers_with_crypto, AC_MAP, config)
        # BTC-EUR non ha classe in equilibrium_weights -> peso 0
        btc_idx = tickers_with_crypto.index("BTC-EUR")
        # w_eq per crypto è 0 (ma dopo normalizzazione su quelli con peso>0)
        # In realtà gli asset con classe non in equilibrium_weights hanno peso 0
        # Il peso finale normalizzato mette tutto sugli altri asset
        assert bl.w_eq[btc_idx] == 0.0

    def test_integration_with_filter_params(self):
        """estimate_parameters con BL filtra cripto correttamente."""
        returns = _make_returns()
        ac_map = AC_MAP.copy()

        params = estimate_parameters(
            returns,
            mean_method="black_litterman",
            cov_method="ledoit_wolf",
            asset_class_map=ac_map,
        )

        # Il risultato include TUTTI i ticker (compreso BTC-EUR)
        assert "BTC-EUR" in params.tickers
        assert len(params.tickers) == len(CORE_TICKERS) + 1
        assert np.all(np.isfinite(params.mu))


# ============================================================
# Test 7: Profili feasible con BL
# ============================================================

class TestProfilesFeasible:
    """Tutti i profili restano feasible con mean_method=black_litterman."""

    def test_all_profiles_feasible_bl(self):
        """5 profili devono essere feasible con BL (no view)."""
        returns = _make_returns()
        ac_map = AC_MAP.copy()

        params = estimate_parameters(
            returns,
            mean_method="black_litterman",
            cov_method="ledoit_wolf",
            asset_class_map=ac_map,
        )

        profiles = load_profiles()
        for name in PROFILE_ORDER:
            profile = profiles[name]
            pr = build_portfolio_for_profile(
                profile, params, horizon_years=5, asset_class_map=ac_map,
            )
            assert pr.portfolio.is_feasible(), f"Profilo {name} non feasible con BL"

            # Verifica vol <= tetto
            if pr.effective_vol_ceiling is not None:
                port_vol = pr.portfolio.stats["volatility"]
                assert port_vol <= pr.effective_vol_ceiling + 1e-3, (
                    f"Profilo {name}: vol {port_vol:.4f} > tetto {pr.effective_vol_ceiling:.4f}"
                )


# ============================================================
# Test aggiuntivi: parsing view e configurazione
# ============================================================

class TestParseViews:
    """Test per il parsing delle view."""

    def test_absolute_view_single_asset(self):
        views = [{"type": "absolute", "assets": ["CSSPX.MI"], "value": 0.07}]
        P, Q = parse_views(views, CORE_TICKERS)
        assert P.shape == (1, len(CORE_TICKERS))
        assert Q.shape == (1,)
        idx = CORE_TICKERS.index("CSSPX.MI")
        assert P[0, idx] == 1.0
        assert Q[0] == 0.07

    def test_relative_view(self):
        views = [{
            "type": "relative",
            "long_assets": ["CSSPX.MI"],
            "short_assets": ["SXR8.DE"],
            "value": 0.02,
        }]
        P, Q = parse_views(views, CORE_TICKERS)
        assert P.shape == (1, len(CORE_TICKERS))
        idx_long = CORE_TICKERS.index("CSSPX.MI")
        idx_short = CORE_TICKERS.index("SXR8.DE")
        assert P[0, idx_long] == 1.0
        assert P[0, idx_short] == -1.0
        assert Q[0] == 0.02

    def test_unknown_asset_ignored(self):
        views = [{"type": "absolute", "assets": ["UNKNOWN"], "value": 0.10}]
        P, Q = parse_views(views, CORE_TICKERS)
        assert P.shape == (0, len(CORE_TICKERS))

    def test_empty_views(self):
        P, Q = parse_views([], CORE_TICKERS)
        assert P.shape == (0, len(CORE_TICKERS))
        assert Q.shape == (0,)


class TestEquilibriumWeights:
    """Test per la costruzione dei pesi di equilibrio."""

    def test_weights_sum_to_one(self):
        w = build_equilibrium_weights(CORE_TICKERS, AC_MAP, {"equity": 0.6, "bond": 0.35, "commodity": 0.05})
        assert abs(w.sum() - 1.0) < 1e-10

    def test_class_proportions(self):
        """I pesi per classe devono riflettere la config."""
        w = build_equilibrium_weights(CORE_TICKERS, AC_MAP, {"equity": 0.6, "bond": 0.35, "commodity": 0.05})

        equity_total = sum(w[i] for i, t in enumerate(CORE_TICKERS) if AC_MAP[t] == "equity")
        bond_total = sum(w[i] for i, t in enumerate(CORE_TICKERS) if AC_MAP[t] == "bond")
        commodity_total = sum(w[i] for i, t in enumerate(CORE_TICKERS) if AC_MAP[t] == "commodity")

        assert abs(equity_total - 0.60) < 1e-10
        assert abs(bond_total - 0.35) < 1e-10
        assert abs(commodity_total - 0.05) < 1e-10

    def test_equal_weight_within_class(self):
        """Dentro ogni classe, i pesi sono uguali."""
        w = build_equilibrium_weights(CORE_TICKERS, AC_MAP, {"equity": 0.6, "bond": 0.35, "commodity": 0.05})

        equity_indices = [i for i, t in enumerate(CORE_TICKERS) if AC_MAP[t] == "equity"]
        equity_weights = [w[i] for i in equity_indices]
        # Tutti uguali dentro la classe
        assert all(abs(ew - equity_weights[0]) < 1e-10 for ew in equity_weights)


class TestMarketCapWeighting:
    """Test per la distribuzione market-cap dentro le classi."""

    def test_market_cap_assigns_only_broad_funds(self):
        """Con market_cap, solo SWDA e EIMI hanno peso equity; regionali = 0."""
        w = build_equilibrium_weights(
            CORE_TICKERS, AC_MAP,
            {"equity": 0.6, "bond": 0.35, "commodity": 0.05},
            within_class_weighting="market_cap",
        )
        # SWDA e EIMI devono avere peso > 0
        assert w[CORE_TICKERS.index("SWDA.MI")] > 0
        assert w[CORE_TICKERS.index("EIMI.MI")] > 0
        # Regionali devono avere peso 0
        for t in ["CSSPX.MI", "SXR8.DE"]:
            assert w[CORE_TICKERS.index(t)] == 0.0

    def test_market_cap_sums_to_one(self):
        w = build_equilibrium_weights(
            CORE_TICKERS, AC_MAP,
            {"equity": 0.6, "bond": 0.35, "commodity": 0.05},
            within_class_weighting="market_cap",
        )
        assert abs(w.sum() - 1.0) < 1e-10

    def test_market_cap_class_totals_preserved(self):
        """Lo split macro equity/bond/commodity resta 60/35/5."""
        w = build_equilibrium_weights(
            CORE_TICKERS, AC_MAP,
            {"equity": 0.6, "bond": 0.35, "commodity": 0.05},
            within_class_weighting="market_cap",
        )
        eq_total = sum(w[i] for i, t in enumerate(CORE_TICKERS) if AC_MAP[t] == "equity")
        bond_total = sum(w[i] for i, t in enumerate(CORE_TICKERS) if AC_MAP[t] == "bond")
        comm_total = sum(w[i] for i, t in enumerate(CORE_TICKERS) if AC_MAP[t] == "commodity")
        assert abs(eq_total - 0.60) < 1e-10
        assert abs(bond_total - 0.35) < 1e-10
        assert abs(comm_total - 0.05) < 1e-10

    def test_market_cap_developed_em_split(self):
        """SWDA/EIMI split reflects 88/12."""
        w = build_equilibrium_weights(
            CORE_TICKERS, AC_MAP,
            {"equity": 0.6, "bond": 0.35, "commodity": 0.05},
            within_class_weighting="market_cap",
        )
        w_swda = w[CORE_TICKERS.index("SWDA.MI")]
        w_eimi = w[CORE_TICKERS.index("EIMI.MI")]
        # Should be 0.6 * 0.88 / 1.0 and 0.6 * 0.12 / 1.0
        assert abs(w_swda - 0.6 * 0.88) < 1e-10
        assert abs(w_eimi - 0.6 * 0.12) < 1e-10

    def test_equal_mode_unchanged(self):
        """Equal mode gives same result as before (retro-compatibility)."""
        w_new = build_equilibrium_weights(
            CORE_TICKERS, AC_MAP,
            {"equity": 0.6, "bond": 0.35, "commodity": 0.05},
            within_class_weighting="equal",
        )
        w_default = build_equilibrium_weights(
            CORE_TICKERS, AC_MAP,
            {"equity": 0.6, "bond": 0.35, "commodity": 0.05},
        )
        np.testing.assert_array_equal(w_new, w_default)

    def test_bond_fallback_to_equal_in_market_cap_mode(self):
        """Bond non hanno pesi market-cap espliciti -> equal-weight dentro la classe."""
        w = build_equilibrium_weights(
            CORE_TICKERS, AC_MAP,
            {"equity": 0.6, "bond": 0.35, "commodity": 0.05},
            within_class_weighting="market_cap",
        )
        bond_indices = [i for i, t in enumerate(CORE_TICKERS) if AC_MAP[t] == "bond"]
        bond_weights = [w[i] for i in bond_indices]
        assert all(abs(bw - bond_weights[0]) < 1e-10 for bw in bond_weights)

    def test_roundtrip_market_cap(self):
        """Roundtrip di equilibrio anche con pesi market-cap."""
        from src.optimizer import get_objective
        from src.constraints import PortfolioConstraints

        cov = _make_cov()
        config = _make_bl_config()
        config.within_class_weighting = "market_cap"

        bl = run_black_litterman(cov, CORE_TICKERS, AC_MAP, config)

        params = ParameterEstimate(
            mu=bl.mu_bl, cov=cov, tickers=CORE_TICKERS,
            metadata={"mean_method": "black_litterman"},
        )
        constraints = PortfolioConstraints(long_only=True, fully_invested=True, max_weight=1.0)
        result = get_objective("max_sharpe").solve(params, constraints)
        assert result.is_feasible()

        w_opt = np.array([result.weights[t] for t in CORE_TICKERS])
        np.testing.assert_allclose(w_opt, bl.w_eq, atol=0.02)

    def test_no_views_market_cap(self):
        """Senza view, mu_BL = Pi + rf anche in market_cap mode."""
        from src.config import get_risk_free_rate
        cov = _make_cov()
        config = _make_bl_config()
        config.within_class_weighting = "market_cap"
        bl = run_black_litterman(cov, CORE_TICKERS, AC_MAP, config)
        rf = get_risk_free_rate()
        np.testing.assert_allclose(bl.mu_bl, bl.pi + rf, atol=1e-12)

    def test_all_profiles_feasible_bl_market_cap(self):
        """5 profili feasible con BL market-cap."""
        returns = _make_returns()
        ac_map = AC_MAP.copy()

        bl_config = BLConfig(
            equilibrium_weights={"equity": 0.6, "bond": 0.35, "commodity": 0.05},
            mu_target=0.055, tau=0.05, delta=None, views=[],
            within_class_weighting="market_cap",
        )

        params = estimate_parameters(
            returns,
            mean_method="black_litterman",
            cov_method="ledoit_wolf",
            asset_class_map=ac_map,
            bl_config=bl_config,
        )

        profiles = load_profiles()
        for name in PROFILE_ORDER:
            pr = build_portfolio_for_profile(
                profiles[name], params, horizon_years=5, asset_class_map=ac_map,
            )
            assert pr.portfolio.is_feasible(), f"Profilo {name} non feasible con BL-MC"
            if pr.effective_vol_ceiling is not None:
                assert pr.portfolio.stats["volatility"] <= pr.effective_vol_ceiling + 1e-3


class TestCalibrateDelta:
    """Test per la calibrazione di delta."""

    def test_delta_reasonable_range(self):
        cov = _make_cov()
        w_eq = build_equilibrium_weights(CORE_TICKERS, AC_MAP, {"equity": 0.6, "bond": 0.35, "commodity": 0.05})
        delta = calibrate_delta(w_eq, cov, mu_target=0.055, rf=0.02)
        assert 0.5 <= delta <= 10.0

    def test_delta_fallback_on_extreme(self):
        """Delta fuori range -> fallback a 2.5."""
        cov = np.eye(8) * 1e-8  # Varianza quasi zero -> delta enorme
        w_eq = np.ones(8) / 8
        delta = calibrate_delta(w_eq, cov, mu_target=0.10, rf=0.02)
        assert delta == 2.5


class TestLoadConfig:
    """Test per il caricamento della configurazione."""

    def test_load_default_config(self):
        config = load_bl_config()
        assert config.tau == 0.05
        assert config.mu_target == 0.055
        assert "equity" in config.equilibrium_weights
        assert isinstance(config.views, list)

    def test_load_missing_file_uses_defaults(self, tmp_path):
        config = load_bl_config(tmp_path / "nonexistent.yaml")
        assert config.tau == 0.05
        assert config.equilibrium_weights == {"equity": 0.60, "bond": 0.35, "commodity": 0.05}


class TestIdzorekOmega:
    """Test per il calcolo di Omega con metodo Idzorek."""

    def test_omega_diagonal(self):
        """Omega deve essere diagonale."""
        cov = _make_cov()
        P = np.zeros((1, len(CORE_TICKERS)))
        P[0, 1] = 1.0  # CSSPX.MI
        Q = np.array([0.07])
        omega = idzorek_omega(P, Q, 0.05, cov, [0.5], 2.5, np.ones(len(CORE_TICKERS)) / len(CORE_TICKERS))
        # Matrice diagonale
        assert omega.shape == (1, 1)
        assert omega[0, 0] > 0

    def test_high_confidence_small_omega(self):
        """Alta confidenza => omega piccola (view più vincolante)."""
        cov = _make_cov()
        P = np.zeros((1, len(CORE_TICKERS)))
        P[0, 1] = 1.0
        Q = np.array([0.07])
        w_eq = np.ones(len(CORE_TICKERS)) / len(CORE_TICKERS)

        omega_high = idzorek_omega(P, Q, 0.05, cov, [0.95], 2.5, w_eq)
        omega_low = idzorek_omega(P, Q, 0.05, cov, [0.10], 2.5, w_eq)

        assert omega_high[0, 0] < omega_low[0, 0]


class TestEstimationIntegration:
    """Test di integrazione con estimate_parameters."""

    def test_bl_returns_parameter_estimate(self):
        """estimate_parameters con BL restituisce un ParameterEstimate valido."""
        returns = _make_returns()
        params = estimate_parameters(
            returns,
            mean_method="black_litterman",
            cov_method="ledoit_wolf",
            asset_class_map=AC_MAP,
        )
        assert isinstance(params, ParameterEstimate)
        assert params.mu.shape == (len(returns.columns),)
        assert params.cov.shape == (len(returns.columns), len(returns.columns))
        assert params.metadata["mean_method"] == "black_litterman"
        assert "bl_delta" in params.metadata
        assert "bl_pi" in params.metadata

    def test_bl_without_asset_class_map_raises(self):
        """BL senza asset_class_map deve dare errore chiaro."""
        returns = _make_returns()
        with pytest.raises(ValueError, match="asset_class_map"):
            estimate_parameters(
                returns,
                mean_method="black_litterman",
                cov_method="ledoit_wolf",
            )

    def test_existing_methods_unchanged(self):
        """bayes_stein e james_stein non sono toccati dall'aggiunta di BL."""
        returns = _make_returns()
        for method in ["historical", "james_stein", "bayes_stein"]:
            params = estimate_parameters(returns, mean_method=method, cov_method="ledoit_wolf")
            assert params.metadata["mean_method"] == method
            assert np.all(np.isfinite(params.mu))


# ============================================================
# Test convenzione view (punto 3 della revisione)
# ============================================================

class TestViewConvention:
    """Verifica la coerenza della convenzione view con Pi + rf.

    Le view assolute sono espresse come RENDIMENTO TOTALE atteso (non excess).
    Internamente BL sottrae rf per lavorare in spazio excess.
    mu_BL restituito = posterior_excess + rf = rendimento totale.

    Conseguenza chiave: una view assoluta pari a mu_BL_eq[X] = Pi[X] + rf
    con confidenza 100% NON deve muovere mu_BL[X], perché coincide
    con l'equilibrio.
    """

    def test_view_equal_to_equilibrium_does_not_move_mu(self):
        """View assoluta = equilibrio (Pi+rf) -> mu_BL invariato."""
        cov = _make_cov()
        config_base = _make_bl_config()
        bl_base = run_black_litterman(cov, CORE_TICKERS, AC_MAP, config_base)

        # La view è esattamente il rendimento totale di equilibrio per CSSPX
        idx = CORE_TICKERS.index("CSSPX.MI")
        view_value = float(bl_base.mu_bl[idx])  # = Pi[CSSPX] + rf

        config_view = _make_bl_config(views=[{
            "type": "absolute",
            "assets": ["CSSPX.MI"],
            "value": view_value,
            "confidence": 99,
        }])
        bl_view = run_black_litterman(cov, CORE_TICKERS, AC_MAP, config_view)

        # mu_BL non deve cambiare (tolleranza numerica)
        np.testing.assert_allclose(bl_view.mu_bl, bl_base.mu_bl, atol=1e-4)

    def test_view_above_equilibrium_raises_mu(self):
        """View assoluta > equilibrio -> mu_BL[X] sale."""
        cov = _make_cov()
        config_base = _make_bl_config()
        bl_base = run_black_litterman(cov, CORE_TICKERS, AC_MAP, config_base)

        idx = CORE_TICKERS.index("CSSPX.MI")
        # View 5 punti sopra l'equilibrio
        view_value = float(bl_base.mu_bl[idx]) + 0.05

        config_view = _make_bl_config(views=[{
            "type": "absolute",
            "assets": ["CSSPX.MI"],
            "value": view_value,
            "confidence": 70,
        }])
        bl_view = run_black_litterman(cov, CORE_TICKERS, AC_MAP, config_view)

        assert bl_view.mu_bl[idx] > bl_base.mu_bl[idx]

    def test_relative_view_rf_invariant(self):
        """View relative sono spread: rf si cancella, non influisce.

        Fissiamo delta per isolare l'effetto: cambiando rf lo spread
        posteriore della view relativa non cambia (rf si cancella nello
        spread lungo-corto).
        """
        from src.config import get_risk_free_rate, set_risk_free_rate
        cov = _make_cov()

        view = {
            "type": "relative",
            "long_assets": ["CSSPX.MI"],
            "short_assets": ["SXR8.DE"],
            "value": 0.03,
            "confidence": 60,
        }
        idx_long = CORE_TICKERS.index("CSSPX.MI")
        idx_short = CORE_TICKERS.index("SXR8.DE")

        original_rf = get_risk_free_rate()
        try:
            spreads = []
            for rf_val in [0.01, 0.03, 0.05]:
                set_risk_free_rate(rf_val)
                # Fissiamo delta per isolare l'effetto di rf sulle view
                config = _make_bl_config(views=[view], delta=3.0)
                bl = run_black_litterman(cov, CORE_TICKERS, AC_MAP, config, rf=rf_val)
                spread = bl.mu_bl[idx_long] - bl.mu_bl[idx_short]
                spreads.append(spread)

            # Tutti gli spread devono essere uguali (rf si cancella)
            np.testing.assert_allclose(spreads, spreads[0], atol=1e-10)
        finally:
            set_risk_free_rate(original_rf)


# ============================================================
# Test: Nuovo schema view e validazione
# ============================================================

class TestNewViewSchema:
    """Test per il nuovo schema delle view (instrument/expected_return/long/short/outperformance)."""

    def test_normalize_absolute_new_schema(self):
        """_normalize_view converte il nuovo schema assoluto al formato interno."""
        view = {
            "type": "absolute",
            "instrument": "EQQQ.DE",
            "expected_return": 0.11,
            "confidence": 0.60,
        }
        norm = _normalize_view(view)
        assert norm["type"] == "absolute"
        assert norm["assets"] == ["EQQQ.DE"]
        assert norm["value"] == 0.11
        assert abs(norm["confidence"] - 0.60) < 1e-10

    def test_normalize_relative_new_schema(self):
        """_normalize_view converte il nuovo schema relativo al formato interno."""
        view = {
            "type": "relative",
            "long": "SXR8.DE",
            "short": "EIMI.MI",
            "outperformance": 0.02,
            "confidence": 0.50,
        }
        norm = _normalize_view(view)
        assert norm["type"] == "relative"
        assert norm["long_assets"] == ["SXR8.DE"]
        assert norm["short_assets"] == ["EIMI.MI"]
        assert norm["value"] == 0.02
        assert abs(norm["confidence"] - 0.50) < 1e-10

    def test_normalize_legacy_confidence_scaling(self):
        """Legacy view con confidence 0-100 viene normalizzata a [0, 1]."""
        view = {
            "type": "absolute",
            "assets": ["CSSPX.MI"],
            "value": 0.07,
            "confidence": 60,
        }
        norm = _normalize_view(view)
        assert abs(norm["confidence"] - 0.60) < 1e-10

    def test_normalize_legacy_low_confidence(self):
        """Legacy view con confidence=1 (1%) viene normalizzata a 0.01."""
        view = {
            "type": "absolute",
            "assets": ["CSSPX.MI"],
            "value": 0.07,
            "confidence": 1,
        }
        norm = _normalize_view(view)
        assert abs(norm["confidence"] - 0.01) < 1e-10

    def test_parse_views_new_schema(self):
        """parse_views accetta il nuovo schema e produce P, Q corretti."""
        views = [
            {"type": "absolute", "instrument": "CSSPX.MI", "expected_return": 0.10, "confidence": 0.7},
        ]
        P, Q = parse_views(views, CORE_TICKERS)
        assert P.shape == (1, len(CORE_TICKERS))
        idx = CORE_TICKERS.index("CSSPX.MI")
        assert P[0, idx] == 1.0
        assert Q[0] == 0.10

    def test_parse_views_relative_new_schema(self):
        """parse_views accetta il nuovo schema relativo."""
        views = [
            {"type": "relative", "long": "SXR8.DE", "short": "EIMI.MI",
             "outperformance": 0.02, "confidence": 0.5},
        ]
        P, Q = parse_views(views, CORE_TICKERS)
        assert P.shape == (1, len(CORE_TICKERS))
        idx_l = CORE_TICKERS.index("SXR8.DE")
        idx_s = CORE_TICKERS.index("EIMI.MI")
        assert P[0, idx_l] == 1.0
        assert P[0, idx_s] == -1.0
        assert Q[0] == 0.02

    def test_run_bl_new_schema_moves_mu(self):
        """run_black_litterman con view in nuovo schema muove mu."""
        cov = _make_cov()
        config_eq = _make_bl_config()
        bl_eq = run_black_litterman(cov, CORE_TICKERS, AC_MAP, config_eq)

        config_view = _make_bl_config(views=[
            {"type": "absolute", "instrument": "CSSPX.MI",
             "expected_return": 0.15, "confidence": 0.80},
        ])
        bl_view = run_black_litterman(cov, CORE_TICKERS, AC_MAP, config_view)

        # CSSPX.MI deve avere un mu superiore con la view
        idx = CORE_TICKERS.index("CSSPX.MI")
        assert bl_view.mu_bl[idx] > bl_eq.mu_bl[idx]


class TestValidateView:
    """Test per validate_view e validate_views."""

    def test_valid_absolute(self):
        errs = validate_view(
            {"type": "absolute", "instrument": "CSSPX.MI",
             "expected_return": 0.10, "confidence": 0.6},
            set(CORE_TICKERS),
        )
        assert errs == []

    def test_valid_relative(self):
        errs = validate_view(
            {"type": "relative", "long": "SXR8.DE", "short": "EIMI.MI",
             "outperformance": 0.02, "confidence": 0.5},
            set(CORE_TICKERS),
        )
        assert errs == []

    def test_missing_type(self):
        errs = validate_view({"instrument": "X", "confidence": 0.5}, set(CORE_TICKERS))
        assert any("type" in e for e in errs)

    def test_unknown_ticker(self):
        errs = validate_view(
            {"type": "absolute", "instrument": "FAKE.XX",
             "expected_return": 0.10, "confidence": 0.5},
            set(CORE_TICKERS),
        )
        assert any("FAKE.XX" in e for e in errs)

    def test_missing_confidence(self):
        errs = validate_view(
            {"type": "absolute", "instrument": "CSSPX.MI", "expected_return": 0.10},
            set(CORE_TICKERS),
        )
        assert any("confidence" in e for e in errs)

    def test_missing_value(self):
        errs = validate_view(
            {"type": "absolute", "instrument": "CSSPX.MI", "confidence": 0.5},
            set(CORE_TICKERS),
        )
        assert any("expected_return" in e.lower() or "value" in e.lower() for e in errs)

    def test_relative_missing_short(self):
        errs = validate_view(
            {"type": "relative", "long": "SXR8.DE",
             "outperformance": 0.02, "confidence": 0.5},
            set(CORE_TICKERS),
        )
        assert any("short" in e.lower() for e in errs)

    def test_validate_views_multiple(self):
        views = [
            {"type": "absolute", "instrument": "CSSPX.MI",
             "expected_return": 0.10, "confidence": 0.6},
            {"type": "absolute", "instrument": "FAKE.XX",
             "expected_return": 0.10, "confidence": 0.6},
        ]
        errs = validate_views(views, CORE_TICKERS)
        assert len(errs) == 1
        assert "View 2" in errs[0]
        assert "FAKE.XX" in errs[0]

    def test_legacy_confidence_accepted(self):
        """Legacy confidence 0-100 e' accettata dalla validazione."""
        errs = validate_view(
            {"type": "absolute", "assets": ["CSSPX.MI"],
             "value": 0.10, "confidence": 60},
            set(CORE_TICKERS),
        )
        assert errs == []


class TestViewImpact:
    """Test per build_view_impact (logica dashboard)."""

    def test_no_views_no_delta(self):
        """Senza view, mu_delta deve essere ~zero."""
        from src.dashboard_data import build_view_impact
        returns = _make_returns()
        vi = build_view_impact(returns, [], profile_name="bilanciato")
        for t in vi.tickers:
            assert abs(vi.mu_delta[t]) < 1e-10

    def test_absolute_view_moves_mu(self):
        """Con una view assoluta, mu_posterior deve differire da mu_equilibrium."""
        from src.dashboard_data import build_view_impact
        returns = _make_returns()
        views = [
            {"type": "absolute", "instrument": "CSSPX.MI",
             "expected_return": 0.15, "confidence": 0.80},
        ]
        vi = build_view_impact(returns, views, profile_name="bilanciato")
        # mu di CSSPX.MI deve essere piu' alto
        assert vi.mu_delta["CSSPX.MI"] > 0.005

    def test_validation_errors_reported(self):
        """View con ticker invalido genera validation_errors."""
        from src.dashboard_data import build_view_impact
        returns = _make_returns()
        views = [
            {"type": "absolute", "instrument": "FAKE.XX",
             "expected_return": 0.10, "confidence": 0.5},
        ]
        vi = build_view_impact(returns, views, profile_name="bilanciato")
        assert len(vi.validation_errors) > 0
