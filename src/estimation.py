"""
Pipeline di stima dei parametri (Fase 2).

Orchestra: preparazione dati -> stima mu -> stima Sigma -> validazione.

OUTPUT (contratto per la Fase 3 - ottimizzatore):
    ParameterEstimate con:
    - mu: np.ndarray, vettore rendimenti attesi annualizzati (p,)
    - cov: np.ndarray, matrice di covarianza annualizzata (p, p)
    - tickers: list[str], nomi strumenti (stesso ordine di mu e cov)
    - metadata: dict con stimatori usati, finestra, ann_factor, shrinkage, ecc.
"""

import logging
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from .mean_estimators import MeanEstimator, MeanEstimate, get_mean_estimator
from .cov_estimators import CovarianceEstimator, CovarianceEstimate, get_cov_estimator

logger = logging.getLogger(__name__)

# Soglie per segnalare rendimenti attesi "assurdi" (annualizzati)
MU_WARN_LOW = -0.50   # -50% annuo
MU_WARN_HIGH = 1.00   # +100% annuo

# Soglia minima di storia per stime affidabili
MIN_HISTORY_DAYS = 252  # ~1 anno


@dataclass
class ParameterEstimate:
    """Contratto di output della Fase 2.

    Questo oggetto sarà l'input della Fase 3 (ottimizzatore).

    Attributi:
        mu: vettore rendimenti attesi annualizzati, shape (p,)
        cov: matrice di covarianza annualizzata, shape (p, p)
        tickers: lista di ticker, lunghezza p
        metadata: dizionario con informazioni sulle stime
    """
    mu: np.ndarray
    cov: np.ndarray
    tickers: list[str]
    returns: np.ndarray | None = None   # Rendimenti giornalieri (S, p) per CVaR storico
    metadata: dict = field(default_factory=dict)

    @property
    def n_assets(self) -> int:
        return len(self.tickers)

    def volatilities(self) -> np.ndarray:
        """Volatilità annualizzate (radice della diagonale di cov)."""
        return np.sqrt(np.diag(self.cov))

    def correlation_matrix(self) -> np.ndarray:
        """Matrice di correlazione derivata dalla covarianza."""
        vols = self.volatilities()
        outer = np.outer(vols, vols)
        # Evita divisione per zero
        outer[outer == 0] = 1.0
        return self.cov / outer


CRYPTO_ASSET_CLASS = "crypto"


def filter_params(
    params: "ParameterEstimate",
    exclude_tickers: set[str],
) -> "ParameterEstimate":
    """Crea un ParameterEstimate escludendo i ticker specificati.

    Usato da profiles e core_satellite per rimuovere le cripto
    dall'ottimizzazione (le cripto entrano solo come satellite).
    """
    keep_idx = [
        i for i, t in enumerate(params.tickers)
        if t not in exclude_tickers
    ]
    if not keep_idx:
        raise ValueError("Nessun ticker rimanente dopo il filtro")

    returns = None
    if params.returns is not None:
        returns = params.returns[:, keep_idx]

    return ParameterEstimate(
        mu=params.mu[keep_idx],
        cov=params.cov[np.ix_(keep_idx, keep_idx)],
        tickers=[params.tickers[i] for i in keep_idx],
        returns=returns,
        metadata={**params.metadata, "filtered_out": sorted(exclude_tickers)},
    )


def get_crypto_tickers(
    tickers: list[str],
    asset_class_map: dict[str, str],
) -> set[str]:
    """Restituisce i ticker classificati come crypto."""
    return {
        t for t in tickers
        if asset_class_map.get(t) == CRYPTO_ASSET_CLASS
    }


def infer_ann_factor(returns: pd.DataFrame) -> int:
    """Ricava il fattore di annualizzazione dalla frequenza osservata dei dati.

    Conta il numero medio di osservazioni per anno nei dati.
    Per dati business-day standard, sarà ~252.
    Per dati settimanali ~52, mensili ~12.

    Se i dati coprono meno di 1 anno, stima dalla frequenza mediana.
    """
    idx = returns.index
    if len(idx) < 2:
        logger.warning("Meno di 2 osservazioni, uso 252 come default")
        return 252

    # Frequenza mediana in giorni calendario
    diffs = pd.Series(idx).diff().dropna().dt.days
    median_gap = diffs.median()

    if median_gap <= 1.5:
        # Dati business-day (mediana=1: lun-ven gap=1, ven-lun gap=3, mediana=1)
        ann = 252
    elif median_gap <= 5:
        # Dati giornalieri con weekend (mediana ~2-3) o bday rari
        ann = 252
    elif median_gap <= 8:
        # Dati settimanali (mediana=7)
        ann = 52
    elif median_gap <= 35:
        # Dati mensili (mediana ~30)
        ann = 12
    else:
        ann = max(1, int(365 / median_gap))

    logger.info(f"Frequenza dati: gap mediano {median_gap:.1f} giorni -> "
                f"ann_factor={ann}")
    return ann


def prepare_returns(
    returns: pd.DataFrame,
    as_of: date | None = None,
    window_days: int | None = None,
) -> pd.DataFrame:
    """Prepara i rendimenti per la stima: taglia alla data e alla finestra.

    Parametri:
        returns: rendimenti giornalieri dal DataBundle
        as_of: data di riferimento (anti-lookahead). Se None, usa l'ultima data.
        window_days: numero di giorni di finestra da usare. Se None, usa tutto.

    Restituisce:
        DataFrame di rendimenti puliti (no NaN, no prima riga NaN).
    """
    # Anti-lookahead: usa solo dati fino a as_of
    if as_of is not None:
        returns = returns.loc[:pd.Timestamp(as_of)]

    # Rimuovi prima riga (NaN da pct_change) e eventuali NaN residui
    returns = returns.dropna()

    # Applica finestra
    if window_days is not None and len(returns) > window_days:
        returns = returns.iloc[-window_days:]

    return returns


def validate_estimates(
    mu_est: MeanEstimate,
    cov_est: CovarianceEstimate,
    sample_cov_cond: float | None = None,
) -> list[str]:
    """Validazione automatica delle stime. Restituisce lista di problemi trovati.

    Controlli:
    - Sigma simmetrica e PSD (autovalori >= 0)
    - Condition number loggato e confrontato con sample
    - Shrinkage intensity in [0, 1]
    - Mu: nessun valore fuori scala
    - Sanity sugli shrinkage
    """
    issues = []
    mu = mu_est.mu
    cov = cov_est.cov
    tickers = mu_est.tickers

    # 1. Simmetria di Sigma
    if not np.allclose(cov, cov.T, atol=1e-10):
        issues.append("ERRORE: Sigma non è simmetrica")
        logger.error("Sigma non è simmetrica")

    # 2. Semidefinita positiva (autovalori >= 0)
    eigenvalues = np.linalg.eigvalsh(cov)
    min_eig = eigenvalues.min()
    tol_psd = -1e-8  # Tolleranza numerica
    if min_eig < tol_psd:
        msg = f"ERRORE: Sigma non è PSD (autovalore minimo: {min_eig:.2e})"
        issues.append(msg)
        logger.error(msg)
    else:
        logger.info(f"Sigma PSD OK (autovalore minimo: {min_eig:.2e})")

    # 3. Condition number
    cond = cov_est.condition_number
    logger.info(f"Condition number di Sigma ({cov_est.method}): {cond:.1f}")
    if sample_cov_cond is not None and cov_est.method != "sample":
        if cond < sample_cov_cond:
            logger.info(f"Shrinkage ha migliorato il condizionamento: "
                        f"{sample_cov_cond:.1f} -> {cond:.1f}")
        else:
            msg = (f"AVVISO: shrinkage non ha migliorato il condizionamento "
                   f"({sample_cov_cond:.1f} -> {cond:.1f})")
            issues.append(msg)
            logger.warning(msg)

    # 4. Shrinkage intensity in [0, 1]
    for label, alpha in [("mu", mu_est.shrinkage_intensity),
                         ("cov", cov_est.shrinkage_intensity)]:
        if not (0.0 <= alpha <= 1.0):
            msg = f"ERRORE: shrinkage intensity {label} fuori [0,1]: {alpha:.4f}"
            issues.append(msg)
            logger.error(msg)

    # 5. Mu: valori ragionevoli
    for i, ticker in enumerate(tickers):
        if mu[i] < MU_WARN_LOW or mu[i] > MU_WARN_HIGH:
            msg = (f"AVVISO: mu annualizzato di {ticker} = {mu[i]:.2%} "
                   f"fuori range [{MU_WARN_LOW:.0%}, {MU_WARN_HIGH:.0%}]")
            issues.append(msg)
            logger.warning(msg)

    if not issues:
        logger.info("Validazione stime: PASSATA (nessun problema)")

    return issues


def estimate_parameters(
    returns: pd.DataFrame,
    mean_method: str = "james_stein",
    cov_method: str = "ledoit_wolf",
    as_of: date | None = None,
    window_days: int | None = None,
    asset_class_map: dict[str, str] | None = None,
    bl_config=None,
) -> ParameterEstimate:
    """Pipeline completa di stima dei parametri.

    Parametri:
        returns: rendimenti giornalieri dal DataBundle
        mean_method: nome dello stimatore di mu (historical, james_stein, bayes_stein,
                     black_litterman)
        cov_method: nome dello stimatore di cov (sample, ledoit_wolf, oas)
        as_of: data di riferimento (anti-lookahead)
        window_days: finestra in giorni di trading
        asset_class_map: ticker -> asset_class (richiesto per black_litterman)
        bl_config: configurazione Black-Litterman (opzionale, default da YAML)

    Restituisce:
        ParameterEstimate con mu, cov, tickers, metadata
    """
    # 1. Prepara rendimenti
    ret = prepare_returns(returns, as_of=as_of, window_days=window_days)

    n_obs = len(ret)
    logger.info(f"Stima parametri: {n_obs} osservazioni, "
                f"{len(ret.columns)} asset, "
                f"periodo {ret.index[0].date()} -> {ret.index[-1].date()}")

    # Avviso se storia insufficiente
    if n_obs < MIN_HISTORY_DAYS:
        logger.warning(f"ATTENZIONE: solo {n_obs} osservazioni "
                       f"(minimo consigliato: {MIN_HISTORY_DAYS}). "
                       f"Le stime potrebbero essere inaffidabili.")

    # Controllo per strumenti con troppi pochi dati
    for col in ret.columns:
        valid = ret[col].notna().sum()
        if valid < MIN_HISTORY_DAYS:
            logger.warning(f"{col}: solo {valid} rendimenti validi "
                           f"(minimo consigliato: {MIN_HISTORY_DAYS})")

    # 2. Ricava il fattore di annualizzazione dalla frequenza dei dati
    ann_factor = infer_ann_factor(ret)

    # 3. Stima Sigma (+ sample per confronto condizionamento)
    cov_estimator = get_cov_estimator(cov_method)
    cov_est = cov_estimator.estimate(ret, ann_factor)

    # Calcola anche la covarianza campionaria per confronto
    sample_cov_cond = None
    if cov_method != "sample":
        from .cov_estimators import SampleCovariance
        sample_est = SampleCovariance().estimate(ret, ann_factor)
        sample_cov_cond = sample_est.condition_number

    # 4. Stima mu
    if mean_method == "black_litterman":
        # Black-Litterman: mu da reverse optimization + view
        from .black_litterman import run_black_litterman, load_bl_config, BLConfig

        if asset_class_map is None:
            raise ValueError(
                "asset_class_map è richiesto per mean_method='black_litterman'"
            )

        if bl_config is None:
            bl_config = load_bl_config()

        bl_result = run_black_litterman(
            cov=cov_est.cov,
            tickers=list(ret.columns),
            asset_class_map=asset_class_map,
            config=bl_config,
        )

        mu = bl_result.mu_bl
        tickers = list(ret.columns)
        mean_shrinkage = 0.0  # BL non usa shrinkage classico

        # Validazione mu BL
        issues = []
        for i, ticker in enumerate(tickers):
            if mu[i] < MU_WARN_LOW or mu[i] > MU_WARN_HIGH:
                msg = (f"AVVISO: mu_BL di {ticker} = {mu[i]:.2%} "
                       f"fuori range [{MU_WARN_LOW:.0%}, {MU_WARN_HIGH:.0%}]")
                issues.append(msg)
                logger.warning(msg)

        # Check Sigma
        eigenvalues = np.linalg.eigvalsh(cov_est.cov)
        if eigenvalues.min() < -1e-8:
            issues.append("ERRORE: Sigma non è PSD")

        # Metadata BL
        bl_metadata = {
            "bl_delta": bl_result.delta,
            "bl_tau": bl_result.tau,
            "bl_mu_target": bl_result.mu_target,
            "bl_w_eq": {t: float(bl_result.w_eq[i]) for i, t in enumerate(tickers)},
            "bl_pi": {t: float(bl_result.pi[i]) for i, t in enumerate(tickers)},
            "bl_mu_bl": {t: float(bl_result.mu_bl[i]) for i, t in enumerate(tickers)},
            "bl_deviation": {
                t: float(bl_result.mu_bl[i] - bl_result.pi[i])
                for i, t in enumerate(tickers)
            },
            "bl_n_views": bl_result.views_P.shape[0] if bl_result.views_P is not None else 0,
        }
        if bl_result.posterior_cov is not None:
            bl_metadata["bl_posterior_cov_diag"] = {
                t: float(bl_result.posterior_cov[i, i])
                for i, t in enumerate(tickers)
            }

        metadata = {
            "mean_method": mean_method,
            "cov_method": cov_method,
            "mean_shrinkage": mean_shrinkage,
            "cov_shrinkage": cov_est.shrinkage_intensity,
            "ann_factor": ann_factor,
            "n_observations": n_obs,
            "date_start": str(ret.index[0].date()),
            "date_end": str(ret.index[-1].date()),
            "condition_number": cov_est.condition_number,
            "condition_number_sample": sample_cov_cond,
            "validation_issues": issues,
            **bl_metadata,
        }

        return ParameterEstimate(
            mu=mu,
            cov=cov_est.cov,
            tickers=tickers,
            returns=ret.values,
            metadata=metadata,
        )

    else:
        # Stimatori classici (historical, james_stein, bayes_stein)
        mean_estimator = get_mean_estimator(mean_method)
        mu_est = mean_estimator.estimate(ret, ann_factor)

        # 5. Validazione
        issues = validate_estimates(mu_est, cov_est, sample_cov_cond)

        # 6. Assembla output
        metadata = {
            "mean_method": mean_method,
            "cov_method": cov_method,
            "mean_shrinkage": mu_est.shrinkage_intensity,
            "cov_shrinkage": cov_est.shrinkage_intensity,
            "ann_factor": ann_factor,
            "n_observations": n_obs,
            "date_start": str(ret.index[0].date()),
            "date_end": str(ret.index[-1].date()),
            "condition_number": cov_est.condition_number,
            "condition_number_sample": sample_cov_cond,
            "validation_issues": issues,
        }

        return ParameterEstimate(
            mu=mu_est.mu,
            cov=cov_est.cov,
            tickers=mu_est.tickers,
            returns=ret.values,
            metadata=metadata,
        )
