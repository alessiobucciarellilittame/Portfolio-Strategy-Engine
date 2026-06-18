"""Test per la costruzione core-satellite."""

import numpy as np
import pytest

from src.estimation import ParameterEstimate, filter_params, CRYPTO_ASSET_CLASS
from src.profiles import ProfileConfig, load_profiles
from src.core_satellite import (
    CoreSatelliteResult,
    build_core_satellite,
    _filter_params,
    DEFAULT_SATELLITE,
    BTC_ETH_SATELLITE,
)


# ============================================================
# Helper: parametri sintetici con crypto
# ============================================================

def _make_params(p=10, seed=42):
    """ParameterEstimate realistico con 4 equity, 3 bond, 1 commodity, 2 crypto."""
    tickers = [
        "SWDA.MI", "CSSPX.MI", "SXR8.DE", "EIMI.MI",
        "IBGS.MI", "XGLE.MI", "IEAC.MI", "SGLD.MI",
        "BTC-EUR", "ETH-EUR",
    ][:p]
    mu = np.array([
        0.08, 0.10, 0.09, 0.06,
        0.03, 0.04, 0.05, 0.12,
        0.40, 0.30,
    ])[:p]
    vols = np.array([
        0.12, 0.13, 0.12, 0.14,
        0.02, 0.06, 0.04, 0.13,
        0.50, 0.55,
    ])[:p]
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
    return ParameterEstimate(mu=mu, cov=cov, tickers=tickers)


def _ac_map():
    return {
        "SWDA.MI": "equity", "CSSPX.MI": "equity",
        "SXR8.DE": "equity", "EIMI.MI": "equity",
        "IBGS.MI": "bond", "XGLE.MI": "bond", "IEAC.MI": "bond",
        "SGLD.MI": "commodity",
        "BTC-EUR": "crypto", "ETH-EUR": "crypto",
    }


def _bilanciato():
    return ProfileConfig(
        name="bilanciato",
        description="Test",
        vol_ceiling=0.11,
        max_weight=0.25,
        objective="max_return",
        group_limits={
            "equity": (0.0, 0.60),
            "bond": (0.10, 0.80),
            "commodity": (0.0, 0.20),
            "crypto": (0.0, 0.05),
        },
    )


def _conservativo():
    return ProfileConfig(
        name="conservativo",
        description="Test",
        vol_ceiling=0.05,
        max_weight=0.30,
        objective="max_return",
        group_limits={
            "equity": (0.0, 0.20),
            "bond": (0.40, 1.0),
            "commodity": (0.0, 0.15),
            "crypto": (0.0, 0.0),
        },
    )


# ============================================================
# Test filtro parametri
# ============================================================

class TestFilterParams:
    def test_excludes_tickers(self):
        params = _make_params()
        filtered = _filter_params(params, {"BTC-EUR", "ETH-EUR"})
        assert "BTC-EUR" not in filtered.tickers
        assert "ETH-EUR" not in filtered.tickers
        assert len(filtered.tickers) == 8

    def test_mu_cov_shape(self):
        params = _make_params()
        filtered = _filter_params(params, {"BTC-EUR", "ETH-EUR"})
        assert filtered.mu.shape == (8,)
        assert filtered.cov.shape == (8, 8)

    def test_preserves_values(self):
        """I valori di mu e cov per i ticker rimanenti devono essere invariati."""
        params = _make_params()
        filtered = _filter_params(params, {"BTC-EUR", "ETH-EUR"})
        # SWDA.MI e' il primo ticker in entrambi
        assert filtered.tickers[0] == "SWDA.MI"
        np.testing.assert_allclose(filtered.mu[0], params.mu[0])


# ============================================================
# Test core esclude crypto
# ============================================================

class TestCoreExcludesCrypto:
    def test_no_crypto_in_core(self):
        """Il core non deve MAI contenere ticker crypto."""
        result = build_core_satellite(
            _bilanciato(), _make_params(), _ac_map(), crypto_weight=0.05,
        )
        ac = _ac_map()
        for t, w in result.core_weights.items():
            assert ac.get(t) != "crypto", (
                f"Crypto ticker '{t}' nel core con peso {w:.4f}"
            )

    def test_core_only_traditional(self):
        result = build_core_satellite(
            _bilanciato(), _make_params(), _ac_map(), crypto_weight=0.0,
        )
        ac = _ac_map()
        for t in result.core_weights:
            assert ac.get(t) in ("equity", "bond", "commodity")


# ============================================================
# Test tetto crypto del profilo
# ============================================================

class TestCryptoCap:
    def test_clamp_to_profile_max(self):
        """Se crypto_weight > tetto profilo, deve essere limitato."""
        result = build_core_satellite(
            _bilanciato(), _make_params(), _ac_map(), crypto_weight=0.20,
        )
        # Bilanciato: max crypto = 5%
        assert result.crypto_weight_actual <= 0.05 + 1e-10
        assert result.crypto_weight_requested == 0.20

    def test_clamp_generates_warning(self):
        result = build_core_satellite(
            _bilanciato(), _make_params(), _ac_map(), crypto_weight=0.20,
        )
        clamp_issues = [
            i for i in result.validation_issues if "limitato" in i
        ]
        assert len(clamp_issues) == 1

    def test_within_limit_no_clamp(self):
        result = build_core_satellite(
            _bilanciato(), _make_params(), _ac_map(), crypto_weight=0.03,
        )
        assert result.crypto_weight_actual == 0.03
        assert result.crypto_weight_requested == 0.03
        clamp_issues = [
            i for i in result.validation_issues if "limitato" in i
        ]
        assert len(clamp_issues) == 0


# ============================================================
# Test conservativo: sempre 0% crypto
# ============================================================

class TestConservativo:
    def test_zero_crypto_regardless(self):
        """Il conservativo ha tetto crypto = 0%, qualunque richiesta."""
        for cw in [0.0, 0.01, 0.05, 0.10]:
            result = build_core_satellite(
                _conservativo(), _make_params(), _ac_map(),
                crypto_weight=cw,
            )
            assert result.crypto_weight_actual == 0.0, (
                f"Conservativo con crypto_weight={cw}: "
                f"actual={result.crypto_weight_actual}"
            )
            # Nessun peso crypto nei combinati
            ac = _ac_map()
            crypto_total = sum(
                w for t, w in result.combined_weights.items()
                if ac.get(t) == "crypto"
            )
            assert crypto_total < 1e-10

    def test_no_satellite(self):
        result = build_core_satellite(
            _conservativo(), _make_params(), _ac_map(), crypto_weight=0.05,
        )
        assert len(result.satellite_weights) == 0


# ============================================================
# Test matematica combinazione
# ============================================================

class TestCombination:
    def test_weights_sum_to_one(self):
        """I pesi combinati devono sommare a 1."""
        for cw in [0.0, 0.01, 0.05]:
            result = build_core_satellite(
                _bilanciato(), _make_params(), _ac_map(),
                crypto_weight=cw,
            )
            w_sum = sum(result.combined_weights.values())
            assert abs(w_sum - 1.0) < 1e-6, (
                f"crypto_weight={cw}: somma={w_sum:.8f}"
            )

    def test_all_non_negative(self):
        result = build_core_satellite(
            _bilanciato(), _make_params(), _ac_map(), crypto_weight=0.05,
        )
        for t, w in result.combined_weights.items():
            assert w >= -1e-6, f"{t}: peso negativo {w}"

    def test_core_scaled_correctly(self):
        """I pesi core nel combinato devono essere core * (1 - cw)."""
        cw = 0.05
        result = build_core_satellite(
            _bilanciato(), _make_params(), _ac_map(), crypto_weight=cw,
        )
        ac = _ac_map()
        for t, w_core in result.core_weights.items():
            w_combined = result.combined_weights.get(t, 0.0)
            expected = w_core * (1 - cw)
            np.testing.assert_allclose(
                w_combined, expected, atol=1e-10,
                err_msg=f"{t}: core={w_core:.6f}, combined={w_combined:.6f}, "
                        f"expected={expected:.6f}",
            )

    def test_satellite_weight_correct(self):
        """Il satellite BTC deve avere esattamente crypto_weight."""
        cw = 0.03
        result = build_core_satellite(
            _bilanciato(), _make_params(), _ac_map(), crypto_weight=cw,
        )
        assert abs(result.satellite_weights.get("BTC-EUR", 0) - cw) < 1e-10
        assert abs(result.combined_weights.get("BTC-EUR", 0) - cw) < 1e-10

    def test_btc_eth_satellite(self):
        """Con satellite BTC/ETH, ciascuno deve avere cw/2."""
        cw = 0.04
        result = build_core_satellite(
            _bilanciato(), _make_params(), _ac_map(),
            crypto_weight=cw,
            satellite_tickers=BTC_ETH_SATELLITE,
        )
        np.testing.assert_allclose(
            result.satellite_weights["BTC-EUR"], 0.02, atol=1e-10,
        )
        np.testing.assert_allclose(
            result.satellite_weights["ETH-EUR"], 0.02, atol=1e-10,
        )


# ============================================================
# Test crypto_weight = 0 equivale al core puro
# ============================================================

class TestZeroCrypto:
    def test_combined_equals_core(self):
        """Con crypto_weight=0 i pesi combinati devono uguagliare il core."""
        result = build_core_satellite(
            _bilanciato(), _make_params(), _ac_map(), crypto_weight=0.0,
        )
        for t in result.core_weights:
            np.testing.assert_allclose(
                result.combined_weights.get(t, 0.0),
                result.core_weights[t],
                atol=1e-10,
                err_msg=f"Peso diverso per {t}",
            )

    def test_stats_match(self):
        """Con crypto_weight=0 le stats combinate devono uguagliare le core."""
        result = build_core_satellite(
            _bilanciato(), _make_params(), _ac_map(), crypto_weight=0.0,
        )
        np.testing.assert_allclose(
            result.combined_stats["expected_return"],
            result.core_stats["expected_return"],
            atol=1e-6,
        )
        np.testing.assert_allclose(
            result.combined_stats["volatility"],
            result.core_stats["volatility"],
            atol=1e-6,
        )

    def test_no_satellite_weights(self):
        result = build_core_satellite(
            _bilanciato(), _make_params(), _ac_map(), crypto_weight=0.0,
        )
        assert len(result.satellite_weights) == 0


# ============================================================
# Test statistiche combinate
# ============================================================

class TestCombinedStats:
    def test_crypto_increases_vol(self):
        """Aggiungere crypto deve aumentare la volatilita'."""
        r0 = build_core_satellite(
            _bilanciato(), _make_params(), _ac_map(), crypto_weight=0.0,
        )
        r5 = build_core_satellite(
            _bilanciato(), _make_params(), _ac_map(), crypto_weight=0.05,
        )
        assert (r5.combined_stats["volatility"]
                > r0.combined_stats["volatility"]), (
            f"Vol con crypto ({r5.combined_stats['volatility']:.4f}) "
            f"<= senza ({r0.combined_stats['volatility']:.4f})"
        )

    def test_crypto_increases_return(self):
        """BTC ha rendimento atteso alto, deve aumentare il rendimento."""
        r0 = build_core_satellite(
            _bilanciato(), _make_params(), _ac_map(), crypto_weight=0.0,
        )
        r5 = build_core_satellite(
            _bilanciato(), _make_params(), _ac_map(), crypto_weight=0.05,
        )
        assert (r5.combined_stats["expected_return"]
                > r0.combined_stats["expected_return"])

    def test_stats_keys_present(self):
        result = build_core_satellite(
            _bilanciato(), _make_params(), _ac_map(), crypto_weight=0.03,
        )
        for key in ["expected_return", "volatility", "sharpe_ratio", "cvar_95"]:
            assert key in result.combined_stats, f"Chiave mancante: {key}"


# ============================================================
# Test feasibility
# ============================================================

class TestFeasibility:
    def test_all_profiles_feasible(self):
        """Core-satellite deve funzionare per tutti i profili."""
        profiles = load_profiles()
        params = _make_params()
        ac = _ac_map()
        for name, profile in profiles.items():
            result = build_core_satellite(
                profile, params, ac, crypto_weight=0.02,
            )
            assert result.profile_result.portfolio.is_feasible(), (
                f"Core infeasible per profilo '{name}'"
            )
            assert abs(sum(result.combined_weights.values()) - 1.0) < 1e-4
