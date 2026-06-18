"""
Stimatori del vettore dei rendimenti attesi (mu).

Interfaccia comune MeanEstimator con implementazioni:
- HistoricalMean: media campionaria
- JamesStein: shrinkage verso la grand mean
- BayesStein: shrinkage verso il portafoglio a minima varianza

Ogni stimatore accetta rendimenti giornalieri e restituisce mu annualizzato.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class MeanEstimate:
    """Risultato di uno stimatore di rendimenti attesi."""
    mu: np.ndarray              # Vettore dei rendimenti attesi annualizzati
    tickers: list[str]          # Nomi degli strumenti (stesso ordine di mu)
    method: str                 # Nome dello stimatore usato
    shrinkage_intensity: float  # Intensità di shrinkage (0.0 per la media storica)
    ann_factor: int             # Fattore di annualizzazione usato


class MeanEstimator(ABC):
    """Interfaccia astratta per gli stimatori di mu."""

    @abstractmethod
    def estimate(self, returns: pd.DataFrame, ann_factor: int) -> MeanEstimate:
        """Stima il vettore dei rendimenti attesi annualizzati.

        Parametri:
            returns: rendimenti giornalieri (righe=date, colonne=ticker), senza NaN
            ann_factor: numero di periodi per anno (ricavato dalla frequenza dei dati)

        Restituisce:
            MeanEstimate con mu annualizzato
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        ...


class HistoricalMean(MeanEstimator):
    """Media campionaria dei rendimenti, annualizzata."""

    @property
    def name(self) -> str:
        return "historical"

    def estimate(self, returns: pd.DataFrame, ann_factor: int) -> MeanEstimate:
        # Media giornaliera × periodi/anno
        # Assunzione: i rendimenti sono i.i.d., quindi E[r_ann] ≈ E[r_daily] × N
        mu_daily = returns.mean().values
        mu = mu_daily * ann_factor

        logger.info(f"HistoricalMean: ann_factor={ann_factor}, nessuno shrinkage")
        return MeanEstimate(
            mu=mu,
            tickers=list(returns.columns),
            method=self.name,
            shrinkage_intensity=0.0,
            ann_factor=ann_factor,
        )


class JamesSteinMean(MeanEstimator):
    """Stimatore James-Stein: shrinkage della media verso la grand mean.

    Il target di shrinkage è la media equipesata di tutti i rendimenti medi
    (grand mean), cioè un unico valore scalare comune a tutti gli asset.

    L'intensità di shrinkage è determinata dalla formula classica:
        alpha = max(0, min(1, (p-2) / (n * sum((mu_i - mu_bar)^2)) ))
    dove p = numero di asset, n = numero di osservazioni.

    mu_shrunk = (1 - alpha) * mu_sample + alpha * mu_bar
    """

    @property
    def name(self) -> str:
        return "james_stein"

    def estimate(self, returns: pd.DataFrame, ann_factor: int) -> MeanEstimate:
        n, p = returns.shape  # n = osservazioni, p = asset
        mu_daily = returns.mean().values
        grand_mean = mu_daily.mean()

        # Somma degli scarti quadratici dalla grand mean
        sum_sq = np.sum((mu_daily - grand_mean) ** 2)

        if sum_sq < 1e-15 or p <= 2:
            # Se tutti i rendimenti medi sono uguali o p <= 2, niente shrinkage
            alpha = 0.0
        else:
            # Varianza media dei rendimenti (proxy per la varianza dello stimatore)
            var_daily = returns.var().mean()
            alpha = ((p - 2) * var_daily / n) / sum_sq
            alpha = max(0.0, min(1.0, alpha))

        mu_shrunk = (1 - alpha) * mu_daily + alpha * grand_mean
        mu_ann = mu_shrunk * ann_factor

        logger.info(f"JamesStein: shrinkage_intensity={alpha:.4f}, ann_factor={ann_factor}")
        return MeanEstimate(
            mu=mu_ann,
            tickers=list(returns.columns),
            method=self.name,
            shrinkage_intensity=alpha,
            ann_factor=ann_factor,
        )


class BayesSteinMean(MeanEstimator):
    """Stimatore Bayes-Stein: shrinkage verso il portafoglio a minima varianza (GMV).

    Il target non è la grand mean ma il rendimento atteso del portafoglio
    a minima varianza, che è lo stimatore più stabile possibile.

    Passo 1: calcola i pesi del portafoglio a minima varianza w_gmv
    Passo 2: il target è mu_gmv = w_gmv' * mu_sample
    Passo 3: applica shrinkage JS verso mu_gmv

    mu_shrunk = (1 - alpha) * mu_sample + alpha * mu_gmv * 1
    """

    @property
    def name(self) -> str:
        return "bayes_stein"

    def estimate(self, returns: pd.DataFrame, ann_factor: int) -> MeanEstimate:
        n, p = returns.shape
        mu_daily = returns.mean().values
        cov_daily = returns.cov().values

        # Pesi del portafoglio a minima varianza (GMV)
        try:
            cov_inv = np.linalg.inv(cov_daily)
        except np.linalg.LinAlgError:
            logger.warning("BayesStein: covarianza singolare, uso pseudo-inversa")
            cov_inv = np.linalg.pinv(cov_daily)

        ones = np.ones(p)
        w_gmv = cov_inv @ ones / (ones @ cov_inv @ ones)

        # Target: rendimento atteso del portafoglio GMV
        mu_gmv = w_gmv @ mu_daily

        # Shrinkage intensity (formula Jorion)
        diff = mu_daily - mu_gmv
        sum_sq = diff @ cov_inv @ diff

        if sum_sq < 1e-15 or p <= 2:
            alpha = 0.0
        else:
            # Formula di Jorion (1986) semplificata
            lambda_js = (p + 2) / ((p + 2) + n * sum_sq)
            alpha = max(0.0, min(1.0, lambda_js))

        mu_shrunk = (1 - alpha) * mu_daily + alpha * mu_gmv
        mu_ann = mu_shrunk * ann_factor

        logger.info(f"BayesStein: shrinkage_intensity={alpha:.4f}, "
                    f"mu_gmv_daily={mu_gmv:.6f}, ann_factor={ann_factor}")
        return MeanEstimate(
            mu=mu_ann,
            tickers=list(returns.columns),
            method=self.name,
            shrinkage_intensity=alpha,
            ann_factor=ann_factor,
        )


# --- Registry per selezione da configurazione ---
MEAN_ESTIMATORS: dict[str, type[MeanEstimator]] = {
    "historical": HistoricalMean,
    "james_stein": JamesSteinMean,
    "bayes_stein": BayesSteinMean,
}


def get_mean_estimator(name: str) -> MeanEstimator:
    """Restituisce un'istanza dello stimatore di media per nome.

    Nomi disponibili: historical, james_stein, bayes_stein
    """
    if name not in MEAN_ESTIMATORS:
        raise ValueError(
            f"Stimatore di media '{name}' non trovato. "
            f"Disponibili: {list(MEAN_ESTIMATORS.keys())}"
        )
    return MEAN_ESTIMATORS[name]()
