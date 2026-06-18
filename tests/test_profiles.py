"""Test per la profilazione cliente (Fase 4)."""

import numpy as np
import pytest

from src.estimation import ParameterEstimate, CRYPTO_ASSET_CLASS
from src.profiles import (
    load_profiles,
    load_horizon_adjustments,
    get_horizon_band,
    profile_to_constraints,
    build_portfolio_for_profile,
    build_all_profiles,
    validate_monotonicity,
    PROFILE_ORDER,
)


def _make_params(p=9, seed=42):
    """Crea ParameterEstimate realistico per i test.

    Volatilità strutturate realisticamente:
    equity ~12%, bond ~4%, commodity ~13%, crypto ~50%
    Correlazioni basse tra classi diverse.
    """
    tickers = [
        "SWDA.MI", "CSSPX.MI", "SXR8.DE", "EIMI.MI",
        "IBGS.MI", "XGLE.MI", "IEAC.MI", "SGLD.MI",
        "BTC-EUR",
    ][:p]
    # Rendimenti attesi annualizzati realistici
    mu = np.array([0.08, 0.10, 0.09, 0.06, 0.03, 0.04, 0.05, 0.12, 0.40])[:p]
    # Volatilità annualizzate realistiche
    vols = np.array([0.12, 0.13, 0.12, 0.14, 0.02, 0.06, 0.04, 0.13, 0.50])[:p]
    # Matrice di correlazione: intra-classe alta, inter-classe bassa
    rng = np.random.RandomState(seed)
    corr = np.eye(p)
    for i in range(p):
        for j in range(i + 1, p):
            # Stessa classe -> correlazione alta
            if i < 4 and j < 4:
                c = 0.7
            elif 4 <= i < 7 and 4 <= j < 7:
                c = 0.6
            elif i >= 8 and j >= 8:
                c = 0.5
            else:
                c = 0.1 + rng.uniform(-0.05, 0.05)
            corr[i, j] = corr[j, i] = c

    # Cov = diag(vols) @ corr @ diag(vols)
    D = np.diag(vols)
    cov = D @ corr @ D

    return ParameterEstimate(mu=mu, cov=cov, tickers=tickers)


def _asset_class_map():
    return {
        "SWDA.MI": "equity", "CSSPX.MI": "equity",
        "SXR8.DE": "equity", "EIMI.MI": "equity",
        "IBGS.MI": "bond", "XGLE.MI": "bond", "IEAC.MI": "bond",
        "SGLD.MI": "commodity",
        "BTC-EUR": "crypto",
    }


# ============================================================
# Test caricamento configurazione
# ============================================================

class TestLoadConfig:
    def test_load_all_profiles(self):
        profiles = load_profiles()
        for name in PROFILE_ORDER:
            assert name in profiles
            assert profiles[name].objective in ("max_return", "max_sharpe")

    def test_load_horizon_adjustments(self):
        adjs = load_horizon_adjustments()
        assert len(adjs) >= 3
        # Devono essere ordinati per max_years
        for i in range(1, len(adjs)):
            assert adjs[i].max_years >= adjs[i - 1].max_years

    def test_conservativo_no_crypto(self):
        """Il profilo conservativo deve avere crypto max = 0."""
        profiles = load_profiles()
        assert profiles["conservativo"].group_limits["crypto"] == (0.0, 0.0)

    def test_vol_ceiling_increasing(self):
        """I tetti di volatilità devono crescere con il profilo."""
        profiles = load_profiles()
        prev_vol = 0.0
        for name in PROFILE_ORDER:
            vol = profiles[name].vol_ceiling
            if vol is not None:
                assert vol >= prev_vol, (
                    f"{name}: vol_ceiling {vol} < precedente {prev_vol}"
                )
                prev_vol = vol


# ============================================================
# Test mappatura profilo -> vincoli
# ============================================================

class TestMapping:
    def test_horizon_short(self):
        band, factor = get_horizon_band(2)
        assert band == "short"
        assert factor < 1.0

    def test_horizon_medium(self):
        band, factor = get_horizon_band(5)
        assert band == "medium"
        assert factor == 1.0

    def test_horizon_long(self):
        band, factor = get_horizon_band(10)
        assert band == "long"
        assert factor > 1.0

    def test_vol_ceiling_adjusted(self):
        """Orizzonte breve deve abbassare il tetto di volatilità."""
        profiles = load_profiles()
        p = profiles["bilanciato"]

        c_short, _, vol_short = profile_to_constraints(p, horizon_years=2)
        c_medium, _, vol_medium = profile_to_constraints(p, horizon_years=5)
        c_long, _, vol_long = profile_to_constraints(p, horizon_years=10)

        assert vol_short < vol_medium < vol_long

    def test_constraints_long_only(self):
        profiles = load_profiles()
        c, _, _ = profile_to_constraints(profiles["moderato"], 5)
        assert c.long_only is True

    def test_group_constraints_passed(self):
        profiles = load_profiles()
        c, _, _ = profile_to_constraints(profiles["conservativo"], 5)
        assert "equity" in c.group_constraints
        assert c.group_constraints["equity"][1] <= 0.30


# ============================================================
# Test ottimizzazione per profilo
# ============================================================

class TestBuildPortfolio:
    def test_all_profiles_feasible(self):
        """Tutti i profili devono produrre un portafoglio feasible."""
        params = _make_params()
        ac = _asset_class_map()
        results = build_all_profiles(params, horizon_years=5, asset_class_map=ac)

        assert len(results) == 5
        for r in results:
            assert r.portfolio.is_feasible(), (
                f"Profilo '{r.profile_name}' infeasible: "
                f"{r.portfolio.metadata}"
            )

    def test_constraints_respected(self):
        """I tetti devono essere rispettati per ogni profilo."""
        params = _make_params()
        ac = _asset_class_map()
        results = build_all_profiles(params, horizon_years=5, asset_class_map=ac)

        for r in results:
            if not r.portfolio.is_feasible():
                continue
            assert len(r.validation_issues) == 0, (
                f"Profilo '{r.profile_name}': {r.validation_issues}"
            )

    def test_conservativo_no_crypto(self):
        """Il portafoglio conservativo non deve contenere crypto."""
        params = _make_params()
        ac = _asset_class_map()
        results = build_all_profiles(params, horizon_years=5, asset_class_map=ac)

        cons = [r for r in results if r.profile_name == "conservativo"][0]
        assert cons.portfolio.is_feasible()

        crypto_weight = sum(
            w for t, w in cons.portfolio.weights.items()
            if ac.get(t) == "crypto"
        )
        assert crypto_weight < 1e-4, f"Crypto nel conservativo: {crypto_weight:.4f}"

    def test_conservativo_mostly_bonds(self):
        """Il conservativo deve essere prevalentemente obbligazionario."""
        params = _make_params()
        ac = _asset_class_map()
        results = build_all_profiles(params, horizon_years=5, asset_class_map=ac)

        cons = [r for r in results if r.profile_name == "conservativo"][0]
        assert cons.portfolio.is_feasible()

        bond_weight = sum(
            w for t, w in cons.portfolio.weights.items()
            if ac.get(t) == "bond"
        )
        assert bond_weight >= 0.30, f"Bond nel conservativo: {bond_weight:.2%}"


# ============================================================
# Test commodity cap e vol target
# ============================================================

class TestNewProfileRules:
    def test_commodity_capped(self):
        """La commodity deve rispettare il tetto (12%) in tutti i profili."""
        params = _make_params()
        ac = _asset_class_map()
        results = build_all_profiles(params, horizon_years=5, asset_class_map=ac)

        for r in results:
            if not r.portfolio.is_feasible():
                continue
            commodity_w = sum(
                w for t, w in r.portfolio.weights.items()
                if ac.get(t) == "commodity"
            )
            max_commodity = r.profile_config.group_limits.get(
                "commodity", (0.0, 1.0)
            )[1]
            assert commodity_w <= max_commodity + 1e-3, (
                f"Profilo '{r.profile_name}': commodity {commodity_w:.2%} "
                f"> tetto {max_commodity:.2%}"
            )

    def test_max_weight_guardrail(self):
        """Nessun singolo asset oltre il guardrail max_weight."""
        params = _make_params()
        ac = _asset_class_map()
        results = build_all_profiles(params, horizon_years=5, asset_class_map=ac)

        for r in results:
            if not r.portfolio.is_feasible():
                continue
            for t, w in r.portfolio.weights.items():
                assert w <= r.profile_config.max_weight + 1e-3, (
                    f"Profilo '{r.profile_name}': {t} peso {w:.2%} "
                    f"> guardrail {r.profile_config.max_weight:.2%}"
                )

    def test_vol_near_target(self):
        """La vol del core deve essere vicina al target.

        Con dati sintetici la vol massima raggiungibile puo' essere inferiore
        ai target piu' alti (es. 14%), quindi usiamo una tolleranza ampia
        per il bound inferiore. Il test principale e' che vol <= target.
        """
        params = _make_params()
        ac = _asset_class_map()
        results = build_all_profiles(params, horizon_years=5, asset_class_map=ac)

        for r in results:
            if not r.portfolio.is_feasible():
                continue
            if r.effective_vol_ceiling is None:
                continue
            vol = r.portfolio.stats["volatility"]
            target = r.effective_vol_ceiling
            # La vol deve essere <= target (il tetto)
            assert vol <= target + 1e-3, (
                f"Profilo '{r.profile_name}': vol {vol:.2%} > target {target:.2%}"
            )
            # Tolleranza ampia per dati sintetici: non piu' di 4pp sotto
            assert vol >= target - 0.04, (
                f"Profilo '{r.profile_name}': vol {vol:.2%} troppo sotto "
                f"target {target:.2%} (differenza {target - vol:.2%})"
            )


# ============================================================
# Test monotonicità
# ============================================================

class TestMonotonicity:
    def test_volatility_monotonic(self):
        """Salendo di profilo, la volatilità non deve diminuire."""
        params = _make_params()
        ac = _asset_class_map()
        results = build_all_profiles(params, horizon_years=5, asset_class_map=ac)

        issues = validate_monotonicity(results)
        assert len(issues) == 0, f"Problemi di monotonicità: {issues}"


# ============================================================
# Test effetto orizzonte
# ============================================================

class TestHorizonEffect:
    def test_short_less_risky_than_long(self):
        """Orizzonte breve deve produrre portafoglio meno rischioso."""
        params = _make_params()
        ac = _asset_class_map()
        profiles = load_profiles()

        result_short = build_portfolio_for_profile(
            profiles["bilanciato"], params, horizon_years=2, asset_class_map=ac
        )
        result_long = build_portfolio_for_profile(
            profiles["bilanciato"], params, horizon_years=10, asset_class_map=ac
        )

        assert result_short.portfolio.is_feasible()
        assert result_long.portfolio.is_feasible()
        assert (result_short.portfolio.stats["volatility"]
                <= result_long.portfolio.stats["volatility"] + 1e-4), (
            f"Short {result_short.portfolio.stats['volatility']:.2%} > "
            f"Long {result_long.portfolio.stats['volatility']:.2%}"
        )

    def test_effective_vol_decreases_for_short(self):
        """Il tetto di vol effettivo deve essere più basso per orizzonte breve."""
        params = _make_params()
        ac = _asset_class_map()
        profiles = load_profiles()

        r_short = build_portfolio_for_profile(
            profiles["moderato"], params, horizon_years=1, asset_class_map=ac
        )
        r_long = build_portfolio_for_profile(
            profiles["moderato"], params, horizon_years=10, asset_class_map=ac
        )

        assert r_short.effective_vol_ceiling < r_long.effective_vol_ceiling


# ============================================================
# Test coerenza: profili escludono crypto (come core-satellite)
# ============================================================

class TestNoCryptoInProfiles:
    def test_no_crypto_in_any_profile(self):
        """Nessun profilo deve avere ticker crypto nei pesi del core."""
        params = _make_params()
        ac = _asset_class_map()
        results = build_all_profiles(params, horizon_years=5, asset_class_map=ac)

        for r in results:
            if not r.portfolio.is_feasible():
                continue
            for t, w in r.portfolio.weights.items():
                assert ac.get(t) != CRYPTO_ASSET_CLASS, (
                    f"Profilo '{r.profile_name}': ticker crypto '{t}' "
                    f"nel core con peso {w:.4f}"
                )

    def test_crypto_constraint_not_in_optimizer(self):
        """profile_to_constraints non deve passare il vincolo crypto."""
        profiles = load_profiles()
        for name in PROFILE_ORDER:
            c, _, _ = profile_to_constraints(profiles[name], 5)
            assert CRYPTO_ASSET_CLASS not in c.group_constraints, (
                f"Profilo '{name}': vincolo crypto presente nei constraints"
            )

    def test_equivalence_with_core_satellite_zero(self):
        """build_portfolio_for_profile deve dare gli stessi pesi core
        di build_core_satellite(crypto_weight=0)."""
        from src.core_satellite import build_core_satellite

        params = _make_params()
        ac = _asset_class_map()
        profiles = load_profiles()

        for name in ["bilanciato", "dinamico"]:
            profile = profiles[name]

            # Via profili
            pr = build_portfolio_for_profile(
                profile, params, horizon_years=5, asset_class_map=ac,
            )
            # Via core-satellite con crypto=0
            cs = build_core_satellite(
                profile, params, ac, crypto_weight=0.0, horizon_years=5,
            )

            assert pr.portfolio.is_feasible()
            assert cs.profile_result.portfolio.is_feasible()

            # I pesi core devono essere identici
            for t in set(pr.portfolio.weights) | set(cs.core_weights):
                w_prof = pr.portfolio.weights.get(t, 0.0)
                w_core = cs.core_weights.get(t, 0.0)
                np.testing.assert_allclose(
                    w_prof, w_core, atol=1e-4,
                    err_msg=f"Profilo '{name}', ticker '{t}': "
                            f"profile={w_prof:.6f} vs core_satellite={w_core:.6f}",
                )
