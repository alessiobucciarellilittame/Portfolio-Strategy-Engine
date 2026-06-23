"""Test per la costruzione core-satellite."""

import numpy as np
import pytest

from src.estimation import (
    ParameterEstimate,
    filter_params,
    CRYPTO_ASSET_CLASS,
    STOCK_ASSET_CLASS,
    SATELLITE_ASSET_CLASSES,
)
from src.profiles import ProfileConfig, load_profiles
from src.core_satellite import (
    CoreSatelliteResult,
    build_core_satellite,
    _filter_params,
    DEFAULT_SATELLITE,
)


# ============================================================
# Helper: parametri sintetici con crypto
# ============================================================

def _make_params(p=9, seed=42):
    """ParameterEstimate realistico con 4 equity, 3 bond, 1 commodity, 1 crypto."""
    tickers = [
        "SWDA.MI", "CSSPX.MI", "SXR8.DE", "EIMI.MI",
        "IBGS.MI", "XGLE.MI", "IEAC.MI", "SGLD.MI",
        "BTC-EUR",
    ][:p]
    mu = np.array([
        0.08, 0.10, 0.09, 0.06,
        0.03, 0.04, 0.05, 0.12,
        0.40,
    ])[:p]
    vols = np.array([
        0.12, 0.13, 0.12, 0.14,
        0.02, 0.06, 0.04, 0.13,
        0.50,
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
        "BTC-EUR": "crypto",
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
        filtered = _filter_params(params, {"BTC-EUR"})
        assert "BTC-EUR" not in filtered.tickers
        assert len(filtered.tickers) == 8

    def test_mu_cov_shape(self):
        params = _make_params()
        filtered = _filter_params(params, {"BTC-EUR"})
        assert filtered.mu.shape == (8,)
        assert filtered.cov.shape == (8, 8)

    def test_preserves_values(self):
        """I valori di mu e cov per i ticker rimanenti devono essere invariati."""
        params = _make_params()
        filtered = _filter_params(params, {"BTC-EUR"})
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


# ============================================================
# Helper: parametri sintetici con crypto + stock
# ============================================================

def _make_params_with_stock(seed=42):
    """ParameterEstimate con 4 equity, 3 bond, 1 commodity, 1 crypto, 2 stock."""
    tickers = [
        "SWDA.MI", "CSSPX.MI", "SXR8.DE", "EIMI.MI",
        "IBGS.MI", "XGLE.MI", "IEAC.MI", "SGLD.MI",
        "BTC-EUR",
        "ENEL.MI", "ENI.MI",
    ]
    p = len(tickers)
    mu = np.array([
        0.08, 0.10, 0.09, 0.06,
        0.03, 0.04, 0.05, 0.12,
        0.40,
        0.07, 0.06,
    ])
    vols = np.array([
        0.12, 0.13, 0.12, 0.14,
        0.02, 0.06, 0.04, 0.13,
        0.50,
        0.25, 0.28,
    ])
    rng = np.random.RandomState(seed)
    corr = np.eye(p)
    for i in range(p):
        for j in range(i + 1, p):
            if i < 4 and j < 4:
                c = 0.7
            elif 4 <= i < 7 and 4 <= j < 7:
                c = 0.6
            else:
                c = 0.1 + rng.uniform(-0.05, 0.05)
            corr[i, j] = corr[j, i] = c
    D = np.diag(vols)
    cov = D @ corr @ D
    return ParameterEstimate(mu=mu, cov=cov, tickers=tickers)


def _ac_map_with_stock():
    return {
        "SWDA.MI": "equity", "CSSPX.MI": "equity",
        "SXR8.DE": "equity", "EIMI.MI": "equity",
        "IBGS.MI": "bond", "XGLE.MI": "bond", "IEAC.MI": "bond",
        "SGLD.MI": "commodity",
        "BTC-EUR": "crypto",
        "ENEL.MI": "stock", "ENI.MI": "stock",
    }


def _dinamico():
    return ProfileConfig(
        name="dinamico",
        description="Test",
        vol_ceiling=0.12,
        max_weight=0.30,
        objective="max_return",
        group_limits={
            "equity": (0.0, 1.0),
            "bond": (0.0, 1.0),
            "commodity": (0.0, 0.20),
            "crypto": (0.0, 0.10),
            "stock": (0.0, 0.15),
        },
    )


def _conservativo_stock():
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
            "stock": (0.0, 0.0),
        },
    )


# ============================================================
# Test satellite stock: quota rispettata e cappata
# ============================================================

class TestStockSatellite:
    def test_stock_weight_respected(self):
        """Il satellite stock deve avere il peso richiesto."""
        result = build_core_satellite(
            _dinamico(), _make_params_with_stock(), _ac_map_with_stock(),
            stock_weight=0.10,
            stock_tickers={"ENEL.MI": 0.6, "ENI.MI": 0.4},
        )
        ac = _ac_map_with_stock()
        stock_total = sum(
            w for t, w in result.combined_weights.items()
            if ac.get(t) == "stock"
        )
        np.testing.assert_allclose(stock_total, 0.10, atol=1e-10)

    def test_stock_clamped_to_profile(self):
        """Stock weight > tetto profilo deve essere limitato."""
        result = build_core_satellite(
            _dinamico(), _make_params_with_stock(), _ac_map_with_stock(),
            stock_weight=0.50,  # > 15% tetto
            stock_tickers={"ENEL.MI": 1.0},
        )
        assert result.stock_weight_actual <= 0.15 + 1e-10
        assert result.stock_weight_requested == 0.50

    def test_stock_not_in_core(self):
        """Le azioni stock non devono apparire nel core."""
        result = build_core_satellite(
            _dinamico(), _make_params_with_stock(), _ac_map_with_stock(),
            stock_weight=0.10,
            stock_tickers={"ENEL.MI": 1.0},
        )
        ac = _ac_map_with_stock()
        for t in result.core_weights:
            assert ac.get(t) not in SATELLITE_ASSET_CLASSES, (
                f"Satellite ticker '{t}' nel core"
            )

    def test_stock_relative_weights(self):
        """I pesi relativi nel satellite stock devono essere rispettati."""
        result = build_core_satellite(
            _dinamico(), _make_params_with_stock(), _ac_map_with_stock(),
            stock_weight=0.10,
            stock_tickers={"ENEL.MI": 0.6, "ENI.MI": 0.4},
        )
        enel = result.combined_weights.get("ENEL.MI", 0)
        eni = result.combined_weights.get("ENI.MI", 0)
        np.testing.assert_allclose(enel, 0.06, atol=1e-10)
        np.testing.assert_allclose(eni, 0.04, atol=1e-10)


# ============================================================
# Test due satelliti insieme (crypto + stock)
# ============================================================

class TestDualSatellite:
    def test_combined_sum_to_one(self):
        """Con crypto + stock i pesi combinati devono sommare a 1."""
        result = build_core_satellite(
            _dinamico(), _make_params_with_stock(), _ac_map_with_stock(),
            crypto_weight=0.05,
            stock_weight=0.10,
            stock_tickers={"ENEL.MI": 1.0},
        )
        w_sum = sum(result.combined_weights.values())
        np.testing.assert_allclose(w_sum, 1.0, atol=1e-6)

    def test_all_non_negative(self):
        """Nessun peso negativo nel combinato."""
        result = build_core_satellite(
            _dinamico(), _make_params_with_stock(), _ac_map_with_stock(),
            crypto_weight=0.05,
            stock_weight=0.10,
            stock_tickers={"ENEL.MI": 0.5, "ENI.MI": 0.5},
        )
        for t, w in result.combined_weights.items():
            assert w >= -1e-6, f"{t}: peso negativo {w}"

    def test_core_scaled_by_total_satellite(self):
        """Core scalato per (1 - crypto - stock)."""
        cw, sw = 0.05, 0.10
        result = build_core_satellite(
            _dinamico(), _make_params_with_stock(), _ac_map_with_stock(),
            crypto_weight=cw,
            stock_weight=sw,
            stock_tickers={"ENEL.MI": 1.0},
        )
        ac = _ac_map_with_stock()
        for t, w_core in result.core_weights.items():
            w_combined = result.combined_weights.get(t, 0.0)
            expected = w_core * (1 - cw - sw)
            np.testing.assert_allclose(
                w_combined, expected, atol=1e-10,
                err_msg=f"{t}: core={w_core:.6f}, combined={w_combined:.6f}",
            )

    def test_sleeves_recorded(self):
        """Ogni sleeve deve essere registrato."""
        result = build_core_satellite(
            _dinamico(), _make_params_with_stock(), _ac_map_with_stock(),
            crypto_weight=0.05,
            stock_weight=0.10,
            stock_tickers={"ENEL.MI": 1.0},
        )
        sleeve_classes = {s.asset_class for s in result.sleeves}
        assert "crypto" in sleeve_classes
        assert "stock" in sleeve_classes


# ============================================================
# Test validazione: ticker nella classe sbagliata
# ============================================================

class TestCrossValidation:
    def test_stock_ticker_in_crypto_rejected(self):
        """Un ticker stock passato come crypto satellite viene rifiutato."""
        result = build_core_satellite(
            _dinamico(), _make_params_with_stock(), _ac_map_with_stock(),
            crypto_weight=0.05,
            satellite_tickers={"ENEL.MI": 1.0},  # stock, non crypto!
        )
        # ENEL.MI rifiutato, crypto forzata a 0
        assert result.crypto_weight_actual == 0.0
        assert any("ENEL.MI" in i for i in result.validation_issues)

    def test_crypto_ticker_in_stock_rejected(self):
        """Un ticker crypto passato come stock satellite viene rifiutato."""
        result = build_core_satellite(
            _dinamico(), _make_params_with_stock(), _ac_map_with_stock(),
            stock_weight=0.10,
            stock_tickers={"BTC-EUR": 1.0},  # crypto, non stock!
        )
        assert result.stock_weight_actual == 0.0
        assert any("BTC-EUR" in i for i in result.validation_issues)


# ============================================================
# Test conservativo: stock forzato a 0
# ============================================================

class TestConservativoStock:
    def test_zero_stock_regardless(self):
        """Il conservativo con tetto stock=0 non ammette azioni."""
        result = build_core_satellite(
            _conservativo_stock(), _make_params_with_stock(), _ac_map_with_stock(),
            stock_weight=0.10,
            stock_tickers={"ENEL.MI": 1.0},
        )
        assert result.stock_weight_actual == 0.0
        ac = _ac_map_with_stock()
        stock_total = sum(
            w for t, w in result.combined_weights.items()
            if ac.get(t) == "stock"
        )
        assert stock_total < 1e-10


# ============================================================
# Test regressione: satellite crypto identico a prima
# ============================================================

class TestCryptoRegression:
    """Verifica che il satellite crypto produca risultati identici
    al vecchio codice (senza stock)."""

    def test_crypto_only_unchanged(self):
        """Con stock_weight=0 il risultato deve essere identico al vecchio."""
        params = _make_params()
        ac = _ac_map()
        profile = _bilanciato()

        result = build_core_satellite(
            profile, params, ac,
            crypto_weight=0.05,
            stock_weight=0.0,
        )

        # Core non contiene crypto
        for t in result.core_weights:
            assert ac.get(t) != "crypto"

        # Somma a 1
        np.testing.assert_allclose(
            sum(result.combined_weights.values()), 1.0, atol=1e-6,
        )

        # BTC ha il peso richiesto
        np.testing.assert_allclose(
            result.combined_weights.get("BTC-EUR", 0), 0.05, atol=1e-10,
        )

        # Core scalato correttamente
        for t, w_core in result.core_weights.items():
            w_combined = result.combined_weights.get(t, 0.0)
            np.testing.assert_allclose(
                w_combined, w_core * 0.95, atol=1e-10,
            )

        # No stock fields
        assert result.stock_weight_actual == 0.0
        assert result.stock_weight_requested == 0.0
