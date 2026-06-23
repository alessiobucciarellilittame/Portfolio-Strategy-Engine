"""
Black-Litterman model implementation.

Calcola i rendimenti attesi posteriori combinando:
1. Prior di equilibrio (reverse optimization da un benchmark strategico)
2. View soggettive opzionali con confidenza Idzorek

Riferimenti:
- Black & Litterman (1992), "Global Portfolio Optimization"
- Idzorek (2005), "A Step-by-Step Guide to the Black-Litterman Model"
- He & Litterman (1999), "The Intuition Behind Black-Litterman"

La covarianza passata all'ottimizzatore NON viene modificata da BL.
Solo mu viene sostituito dal posterior.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import yaml

from .config import get_risk_free_rate

logger = logging.getLogger(__name__)

DEFAULT_BL_CONFIG_PATH = Path(__file__).parent.parent / "config" / "black_litterman.yaml"

# Defaults coerenti col YAML
DEFAULT_EQUILIBRIUM_WEIGHTS = {"equity": 0.60, "bond": 0.35, "commodity": 0.05}
DEFAULT_MU_TARGET = 0.055
DEFAULT_TAU = 0.05
DEFAULT_DELTA = None
DEFAULT_WITHIN_CLASS_WEIGHTING = "equal"

# Pesi market-cap di default per la distribuzione dentro le classi.
# Equity: solo fondi broad non sovrapposti (World + EM).
#   SWDA = MSCI World (~88% dei mercati sviluppati per cap)
#   EIMI = MSCI EM (~12%)
#   I fondi regionali (CSSPX, EQQQ, SXR8, SMEA, SJPA) ricevono peso 0:
#   NON fanno parte del "mercato neutrale", sono strumenti per tilt/view.
#   Peso 0 non li esclude dall'ottimizzazione: ricevono comunque un Π
#   sensato via la covarianza col mercato (Π = δΣw_eq).
# Bond: equal-weight (nessun benchmark cap ovvio per ETF obbligazionari EUR).
# Commodity: un solo strumento (SGLD), irrilevante.
DEFAULT_MARKET_CAP_WEIGHTS: dict[str, float] = {
    "SWDA.MI": 0.88,   # MSCI World (developed)
    "EIMI.MI": 0.12,   # MSCI EM
}


@dataclass
class BLConfig:
    """Configurazione Black-Litterman caricata da YAML."""
    equilibrium_weights: dict[str, float]
    mu_target: float
    tau: float
    delta: float | None
    views: list[dict]
    within_class_weighting: str = "equal"  # "equal" | "market_cap"
    market_cap_weights: dict[str, float] | None = None  # override per market_cap


@dataclass
class BLResult:
    """Risultato del calcolo Black-Litterman."""
    mu_bl: np.ndarray          # Posterior mu (annualizzato)
    pi: np.ndarray             # Rendimenti impliciti di equilibrio
    w_eq: np.ndarray           # Pesi di equilibrio normalizzati
    delta: float               # Risk aversion usata
    tau: float                 # Tau usato
    mu_target: float           # Mu target del benchmark
    posterior_cov: np.ndarray | None  # Covarianza posteriore BL (diagnostica)
    views_P: np.ndarray | None       # Matrice P delle view
    views_Q: np.ndarray | None       # Vettore Q delle view
    omega: np.ndarray | None         # Matrice Omega (confidenza)
    tickers: list[str]


def load_bl_config(path: Path | None = None) -> BLConfig:
    """Carica la configurazione BL dal YAML. Fallback a default se manca."""
    path = path or DEFAULT_BL_CONFIG_PATH
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        logger.info("BL config non trovata, uso defaults")
        data = {}

    if data is None:
        data = {}

    return BLConfig(
        equilibrium_weights=data.get("equilibrium_weights", DEFAULT_EQUILIBRIUM_WEIGHTS),
        mu_target=float(data.get("mu_target", DEFAULT_MU_TARGET)),
        tau=float(data.get("tau", DEFAULT_TAU)),
        delta=data.get("delta"),
        views=data.get("views", []) or [],
        within_class_weighting=data.get("within_class_weighting", DEFAULT_WITHIN_CLASS_WEIGHTING),
        market_cap_weights=data.get("market_cap_weights"),
    )


def build_equilibrium_weights(
    tickers: list[str],
    asset_class_map: dict[str, str],
    class_weights: dict[str, float],
    within_class_weighting: str = "equal",
    market_cap_weights: dict[str, float] | None = None,
) -> np.ndarray:
    """Costruisce i pesi di equilibrio normalizzati.

    Modalità di distribuzione dentro ogni classe (within_class_weighting):
    - "equal": equal-weight tra tutti i membri della classe.
    - "market_cap": usa market_cap_weights per gli asset che hanno un peso
      esplicito; gli altri nella stessa classe ricevono peso 0.
      Peso 0 NON esclude l'asset dall'ottimizzazione: riceve comunque
      un rendimento implicito Π sensato via Π = δΣw_eq.

    Parametri:
        tickers: lista di ticker nel core (senza cripto)
        asset_class_map: ticker -> asset_class
        class_weights: asset_class -> peso target macro (da config)
        within_class_weighting: "equal" | "market_cap"
        market_cap_weights: ticker -> peso relativo dentro la classe (market_cap mode)

    Restituisce:
        Array normalizzato (somma = 1) di pesi di equilibrio.
    """
    n = len(tickers)
    w = np.zeros(n)
    ticker_idx = {t: i for i, t in enumerate(tickers)}

    if within_class_weighting == "market_cap":
        mcw = market_cap_weights or DEFAULT_MARKET_CAP_WEIGHTS
        # Raggruppa per classe
        class_members: dict[str, list[int]] = {}
        for i, t in enumerate(tickers):
            ac = asset_class_map.get(t, "other")
            class_members.setdefault(ac, []).append(i)

        for ac, indices in class_members.items():
            class_w = class_weights.get(ac, 0.0)
            if class_w <= 0 or len(indices) == 0:
                continue

            # Quali asset in questa classe hanno un peso market-cap esplicito?
            mc_indices = [(i, mcw[tickers[i]]) for i in indices if tickers[i] in mcw]

            if mc_indices:
                # Distribuisci il peso della classe secondo i pesi market-cap
                mc_total = sum(mw for _, mw in mc_indices)
                if mc_total > 0:
                    for i, mw in mc_indices:
                        w[i] = class_w * (mw / mc_total)
                # Asset nella classe senza peso esplicito -> peso 0
            else:
                # Nessun asset con peso market-cap in questa classe -> equal-weight
                per_asset = class_w / len(indices)
                for i in indices:
                    w[i] = per_asset
    else:
        # Equal-weight dentro ogni classe (comportamento originale)
        class_members = {}
        for i, t in enumerate(tickers):
            ac = asset_class_map.get(t, "other")
            class_members.setdefault(ac, []).append(i)

        for ac, indices in class_members.items():
            class_w = class_weights.get(ac, 0.0)
            if class_w > 0 and len(indices) > 0:
                per_asset = class_w / len(indices)
                for i in indices:
                    w[i] = per_asset

    # Normalizza
    total = w.sum()
    if total > 0:
        w = w / total
    else:
        w = np.ones(n) / n
        logger.warning("BL: pesi di equilibrio tutti zero, fallback a equal-weight")

    return w


def calibrate_delta(
    w_eq: np.ndarray,
    cov: np.ndarray,
    mu_target: float,
    rf: float,
) -> float:
    """Calibra il parametro di risk aversion delta dall'equilibrio.

    delta = (mu_target - rf) / (w_eq' * Sigma * w_eq)

    Se il risultato è fuori range [0.5, 10], fallback a 2.5 con warning.
    """
    sigma_sq_eq = float(w_eq @ cov @ w_eq)

    if sigma_sq_eq < 1e-10:
        logger.warning("BL: varianza equilibrio ~0, fallback delta=2.5")
        return 2.5

    delta = (mu_target - rf) / sigma_sq_eq

    if delta < 0.5 or delta > 10.0:
        logger.warning(
            f"BL: delta calibrato={delta:.2f} fuori range [0.5, 10], "
            f"fallback a 2.5 (mu_target={mu_target:.3f}, rf={rf:.3f}, "
            f"sigma_sq_eq={sigma_sq_eq:.4f})"
        )
        return 2.5

    logger.info(f"BL: delta calibrato = {delta:.3f}")
    return delta


def compute_implied_returns(
    delta: float,
    cov: np.ndarray,
    w_eq: np.ndarray,
) -> np.ndarray:
    """Calcola i rendimenti impliciti di equilibrio: Pi = delta * Sigma * w_eq."""
    return delta * cov @ w_eq


def validate_view(view: dict, valid_tickers: set[str]) -> list[str]:
    """Valida una singola view e restituisce lista di errori (vuota = ok).

    Schema accettato:
    - Assoluta: {type: "absolute", instrument: "TICKER", expected_return: float, confidence: float}
      oppure (legacy) {type: "absolute", assets: [...], value: float, confidence: float}
    - Relativa: {type: "relative", long: "TICKER", short: "TICKER", outperformance: float, confidence: float}
      oppure (legacy) {type: "relative", long_assets: [...], short_assets: [...], value: float, confidence: float}
    """
    errors = []
    vtype = view.get("type")
    if vtype not in ("absolute", "relative"):
        errors.append(f"type deve essere 'absolute' o 'relative', trovato: {vtype!r}")
        return errors

    # Confidence
    conf = view.get("confidence")
    if conf is None:
        errors.append("campo 'confidence' mancante")
    else:
        c = float(conf)
        if not (0.0 <= c <= 1.0):
            # Accetta anche 0-100 (legacy): se > 1 tratta come percentuale
            if 0.0 <= c <= 100.0:
                pass  # verrà normalizzato in _extract_valid_confidences
            else:
                errors.append(f"confidence deve essere in [0, 1] (o [0, 100]), trovato: {c}")

    if vtype == "absolute":
        # Nuovo schema: instrument + expected_return
        instrument = view.get("instrument")
        assets = view.get("assets")
        value = view.get("expected_return", view.get("value"))

        if instrument is None and assets is None:
            errors.append("view assoluta: serve 'instrument' (o 'assets')")
        elif instrument is not None:
            if instrument not in valid_tickers:
                errors.append(f"instrument '{instrument}' non presente nel core")
        elif assets is not None:
            for a in assets:
                if a not in valid_tickers:
                    errors.append(f"asset '{a}' non presente nel core")

        if value is None:
            errors.append("view assoluta: serve 'expected_return' (o 'value')")

    elif vtype == "relative":
        # Nuovo schema: long + short + outperformance
        long_t = view.get("long")
        short_t = view.get("short")
        long_assets = view.get("long_assets")
        short_assets = view.get("short_assets")
        value = view.get("outperformance", view.get("value"))

        if long_t is None and long_assets is None:
            errors.append("view relativa: serve 'long' (o 'long_assets')")
        elif long_t is not None and long_t not in valid_tickers:
            errors.append(f"long '{long_t}' non presente nel core")

        if short_t is None and short_assets is None:
            errors.append("view relativa: serve 'short' (o 'short_assets')")
        elif short_t is not None and short_t not in valid_tickers:
            errors.append(f"short '{short_t}' non presente nel core")

        if value is None:
            errors.append("view relativa: serve 'outperformance' (o 'value')")

    return errors


def validate_views(views_config: list[dict], tickers: list[str]) -> list[str]:
    """Valida tutte le view. Restituisce lista di errori."""
    valid_tickers = set(tickers)
    all_errors = []
    for i, view in enumerate(views_config):
        errs = validate_view(view, valid_tickers)
        for e in errs:
            all_errors.append(f"View {i + 1}: {e}")
    return all_errors


def _normalize_view(view: dict) -> dict:
    """Normalizza una view dal nuovo schema al formato interno.

    Accetta sia il nuovo schema (instrument/expected_return/long/short/outperformance)
    sia il vecchio (assets/value/long_assets/short_assets).

    La confidenza viene normalizzata a [0, 1]:
    - Nuovo schema (ha 'instrument'/'long'/'short'): gia' in [0, 1]
    - Legacy (ha 'assets'/'long_assets'/'short_assets'): scala [0, 100] -> dividi per 100
    """
    vtype = view.get("type", "absolute")

    # Determina se e' nuovo schema per la normalizzazione della confidenza
    is_new_schema = any(k in view for k in ("instrument", "expected_return", "outperformance"))
    raw_conf = view.get("confidence", 50 if not is_new_schema else 0.5)
    conf = float(raw_conf)
    if not is_new_schema:
        conf = conf / 100.0
    conf = max(0.0, min(1.0, conf))

    if vtype == "absolute":
        instrument = view.get("instrument")
        assets = view.get("assets")
        value = view.get("expected_return", view.get("value"))
        return {
            "type": "absolute",
            "assets": [instrument] if instrument else (assets or []),
            "value": float(value) if value is not None else 0.0,
            "confidence": conf,
        }
    elif vtype == "relative":
        long_t = view.get("long")
        short_t = view.get("short")
        long_assets = view.get("long_assets")
        short_assets = view.get("short_assets")
        value = view.get("outperformance", view.get("value"))
        return {
            "type": "relative",
            "long_assets": [long_t] if long_t else (long_assets or []),
            "short_assets": [short_t] if short_t else (short_assets or []),
            "value": float(value) if value is not None else 0.0,
            "confidence": conf,
        }
    return view


def parse_views(
    views_config: list[dict],
    tickers: list[str],
) -> tuple[np.ndarray, np.ndarray]:
    """Costruisce le matrici P e Q dalle view configurate.

    Accetta sia il nuovo schema (instrument/expected_return) sia il vecchio
    (assets/value). Normalizza internamente.

    Parametri:
        views_config: lista di dizionari
        tickers: lista ticker nel core

    Restituisce:
        (P, Q) dove P è (k, n) e Q è (k,)
    """
    n = len(tickers)
    ticker_idx = {t: i for i, t in enumerate(tickers)}

    P_rows = []
    Q_vals = []

    for raw_view in views_config:
        view = _normalize_view(raw_view)
        vtype = view.get("type", "absolute")
        value = float(view["value"])

        if vtype == "absolute":
            assets = view["assets"]
            row = np.zeros(n)
            count = 0
            for a in assets:
                if a in ticker_idx:
                    row[ticker_idx[a]] = 1.0
                    count += 1
            if count > 1:
                row /= count
            if count > 0:
                P_rows.append(row)
                Q_vals.append(value)
            else:
                logger.warning(f"BL view ignorata: asset {assets} non nel core")

        elif vtype == "relative":
            long_assets = view.get("long_assets", [])
            short_assets = view.get("short_assets", [])
            row = np.zeros(n)

            n_long = sum(1 for a in long_assets if a in ticker_idx)
            n_short = sum(1 for a in short_assets if a in ticker_idx)

            if n_long == 0 or n_short == 0:
                logger.warning(
                    f"BL view relativa ignorata: long={long_assets}, short={short_assets}"
                )
                continue

            for a in long_assets:
                if a in ticker_idx:
                    row[ticker_idx[a]] = 1.0 / n_long
            for a in short_assets:
                if a in ticker_idx:
                    row[ticker_idx[a]] = -1.0 / n_short

            P_rows.append(row)
            Q_vals.append(value)
        else:
            logger.warning(f"BL: tipo view sconosciuto '{vtype}', ignorata")

    if not P_rows:
        return np.empty((0, n)), np.empty(0)

    return np.array(P_rows), np.array(Q_vals)


def idzorek_omega(
    P: np.ndarray,
    Q: np.ndarray,
    tau: float,
    cov: np.ndarray,
    confidences: list[float],
    delta: float,
    w_eq: np.ndarray,
) -> np.ndarray:
    """Calcola la matrice Omega usando il metodo di Idzorek (forma chiusa).

    Per ciascuna view k con confidenza c_k in [0, 1]:
    - Con c_k = 1 la view è vincolante (omega_k -> 0, clamped a 1e-10)
    - Con c_k = 0 la view è ignorata (omega_k -> inf, capped a 1e10)

    Metodo (Idzorek 2005, Appendix A - forma chiusa):
    Per ogni view k, omega_kk viene calibrato affinché il peso dell'asset
    nella view si muova di c_k * (tilt_100% - w_eq) dalla soluzione di equilibrio.

    Formula chiusa:
        p_k = P[k, :]  (riga k di P)
        alpha_k = 1 / (p_k @ (tau * Sigma) @ p_k.T)
        omega_kk = (1 - c_k) / c_k * (p_k @ (tau * Sigma) @ p_k.T)

    Equivalente a:  omega_kk = (1/c_k - 1) * p_k @ (tau * Sigma) @ p_k.T

    Riferimento: Idzorek (2005), "A Step-by-Step Guide to the
    Black-Litterman Model", Appendix A.
    """
    k = P.shape[0]
    omega_diag = np.zeros(k)
    tau_sigma = tau * cov

    for i in range(k):
        p_i = P[i, :]
        view_var = float(p_i @ tau_sigma @ p_i)

        c = confidences[i]
        # Clamp confidenza per evitare singolarità
        c = max(1e-4, min(1.0 - 1e-4, c))

        omega_diag[i] = ((1.0 / c) - 1.0) * view_var

        # Clamp finale per stabilità numerica
        omega_diag[i] = max(omega_diag[i], 1e-10)

    return np.diag(omega_diag)


def compute_posterior(
    pi: np.ndarray,
    cov: np.ndarray,
    tau: float,
    P: np.ndarray,
    Q: np.ndarray,
    omega: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Calcola il posterior Black-Litterman.

    mu_BL = [(tau*Sigma)^-1 + P' Omega^-1 P]^-1 * [(tau*Sigma)^-1 Pi + P' Omega^-1 Q]
    M     = [(tau*Sigma)^-1 + P' Omega^-1 P]^-1   (covarianza posteriore, diagnostica)

    Usa np.linalg.solve per stabilità numerica (niente inversioni esplicite).

    Se non ci sono view (P vuota), mu_BL = Pi.
    """
    n = len(pi)
    tau_sigma = tau * cov

    if P.shape[0] == 0:
        # Nessuna view: posterior = prior
        return pi.copy(), tau_sigma.copy()

    # tau_sigma_inv @ x = solve(tau_sigma, x)
    # Costruisci il sistema: M^-1 = tau_sigma_inv + P' @ Omega_inv @ P
    tau_sigma_inv = np.linalg.solve(tau_sigma, np.eye(n))
    omega_inv = np.linalg.solve(omega, np.eye(P.shape[0]))

    # Precision matrix del posterior
    M_inv = tau_sigma_inv + P.T @ omega_inv @ P

    # Risolvere M_inv @ mu_BL = tau_sigma_inv @ Pi + P' @ omega_inv @ Q
    rhs = tau_sigma_inv @ pi + P.T @ omega_inv @ Q

    mu_bl = np.linalg.solve(M_inv, rhs)
    M = np.linalg.inv(M_inv)

    return mu_bl, M


def run_black_litterman(
    cov: np.ndarray,
    tickers: list[str],
    asset_class_map: dict[str, str],
    config: BLConfig | None = None,
    rf: float | None = None,
) -> BLResult:
    """Esegue il calcolo Black-Litterman completo.

    Parametri:
        cov: matrice di covarianza annualizzata (n, n) - dal cov_estimator
        tickers: lista ticker (solo core, no crypto)
        asset_class_map: ticker -> asset_class
        config: configurazione BL (default: caricata da YAML)
        rf: risk-free rate (default: da config centralizzata)

    Restituisce:
        BLResult con mu_bl (rendimenti TOTALI, non excess) e tutti i dati
        intermedi per diagnostica.

    Nota: Pi = delta * Sigma * w_eq sono rendimenti in ECCESSO (excess returns).
    Il mu_bl restituito è Pi + rf (rendimenti totali), coerente con il
    contratto di ParameterEstimate dove mu = rendimento totale atteso.
    """
    if config is None:
        config = load_bl_config()
    if rf is None:
        rf = get_risk_free_rate()

    n = len(tickers)

    # 1. Pesi di equilibrio
    w_eq = build_equilibrium_weights(
        tickers, asset_class_map, config.equilibrium_weights,
        within_class_weighting=config.within_class_weighting,
        market_cap_weights=config.market_cap_weights,
    )

    # 2. Calibra delta
    if config.delta is not None:
        delta = float(config.delta)
        logger.info(f"BL: delta da config = {delta:.3f}")
    else:
        delta = calibrate_delta(w_eq, cov, config.mu_target, rf)

    # 3. Rendimenti impliciti (excess returns)
    pi = compute_implied_returns(delta, cov, w_eq)

    # 4. Parse view (le view sono in termini di rendimenti totali attesi,
    #    ma la formula BL opera su eccessi; sottraiamo rf dalle view assolute)
    P, Q = parse_views(config.views, tickers)
    # Q contiene rendimenti totali attesi dalla config; converti a excess
    # per il calcolo BL. Per view relative Q è già uno spread (rf si cancella).
    Q_excess = Q.copy()
    if P.shape[0] > 0:
        for i, view in enumerate(_iter_valid_views(config.views, tickers)):
            if view.get("type", "absolute") == "absolute":
                Q_excess[i] = Q[i] - rf

    # 5. Se ci sono view, calcola Omega e posterior
    omega = None
    posterior_cov = None
    if P.shape[0] > 0:
        confidences_valid = _extract_valid_confidences(config.views, tickers)

        if len(confidences_valid) != P.shape[0]:
            logger.warning(
                f"BL: mismatch confidenze ({len(confidences_valid)}) vs view ({P.shape[0]}), "
                "uso 50% per tutte"
            )
            confidences_valid = [0.5] * P.shape[0]

        omega = idzorek_omega(P, Q_excess, config.tau, cov, confidences_valid, delta, w_eq)
        mu_excess_bl, posterior_cov = compute_posterior(pi, cov, config.tau, P, Q_excess, omega)
    else:
        mu_excess_bl = pi.copy()

    # Converti da excess a rendimenti totali
    mu_bl = mu_excess_bl + rf

    return BLResult(
        mu_bl=mu_bl,
        pi=pi,
        w_eq=w_eq,
        delta=delta,
        tau=config.tau,
        mu_target=config.mu_target,
        posterior_cov=posterior_cov,
        views_P=P if P.shape[0] > 0 else None,
        views_Q=Q if Q.shape[0] > 0 else None,
        omega=omega,
        tickers=tickers,
    )


def _iter_valid_views(
    views_config: list[dict],
    tickers: list[str],
):
    """Yield le view normalizzate che parse_views accetterebbe."""
    ticker_set = set(tickers)
    for raw_view in views_config:
        view = _normalize_view(raw_view)
        vtype = view.get("type", "absolute")
        if vtype == "absolute":
            assets = view.get("assets", [])
            if any(a in ticker_set for a in assets):
                yield view
        elif vtype == "relative":
            long_assets = view.get("long_assets", [])
            short_assets = view.get("short_assets", [])
            if any(a in ticker_set for a in long_assets) and any(a in ticker_set for a in short_assets):
                yield view


def _extract_valid_confidences(
    views_config: list[dict],
    tickers: list[str],
) -> list[float]:
    """Estrae le confidenze solo per le view che parse_views accetterebbe.

    Le confidenze sono gia' normalizzate a [0, 1] da _normalize_view.
    """
    ticker_set = set(tickers)
    confidences = []

    for raw_view in views_config:
        view = _normalize_view(raw_view)
        vtype = view.get("type", "absolute")
        c = float(view.get("confidence", 0.5))

        if vtype == "absolute":
            assets = view.get("assets", [])
            if any(a in ticker_set for a in assets):
                confidences.append(c)
        elif vtype == "relative":
            long_assets = view.get("long_assets", [])
            short_assets = view.get("short_assets", [])
            has_long = any(a in ticker_set for a in long_assets)
            has_short = any(a in ticker_set for a in short_assets)
            if has_long and has_short:
                confidences.append(c)

    return confidences
