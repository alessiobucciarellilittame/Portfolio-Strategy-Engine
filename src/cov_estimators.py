"""
Stimatori della matrice di covarianza (Sigma).

Interfaccia comune CovarianceEstimator con implementazioni:
- SampleCovariance: covarianza campionaria
- LedoitWolfCovariance: shrinkage Ledoit-Wolf (via scikit-learn)
- OASCovariance: Oracle Approximating Shrinkage (via scikit-learn)

Ogni stimatore accetta rendimenti giornalieri e restituisce Sigma annualizzata.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
import logging

import numpy as np
import pandas as pd
from sklearn.covariance import LedoitWolf, OAS

logger = logging.getLogger(__name__)


@dataclass
class CovarianceEstimate:
    """Risultato di uno stimatore di covarianza."""
    cov: np.ndarray             # Matrice di covarianza annualizzata (p x p)
    tickers: list[str]          # Nomi degli strumenti (stesso ordine)
    method: str                 # Nome dello stimatore usato
    shrinkage_intensity: float  # Intensità di shrinkage (0.0 per sample)
    ann_factor: int             # Fattore di annualizzazione usato
    condition_number: float     # Numero di condizionamento della matrice


def _condition_number(cov: np.ndarray) -> float:
    """Calcola il numero di condizionamento della matrice."""
    eigenvalues = np.linalg.eigvalsh(cov)
    if eigenvalues.min() <= 0:
        return float("inf")
    return float(eigenvalues.max() / eigenvalues.min())


class CovarianceEstimator(ABC):
    """Interfaccia astratta per gli stimatori di covarianza."""

    @abstractmethod
    def estimate(self, returns: pd.DataFrame, ann_factor: int) -> CovarianceEstimate:
        """Stima la matrice di covarianza annualizzata.

        Parametri:
            returns: rendimenti giornalieri (righe=date, colonne=ticker), senza NaN
            ann_factor: numero di periodi per anno

        Restituisce:
            CovarianceEstimate con covarianza annualizzata
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        ...


class SampleCovariance(CovarianceEstimator):
    """Covarianza campionaria, annualizzata."""

    @property
    def name(self) -> str:
        return "sample"

    def estimate(self, returns: pd.DataFrame, ann_factor: int) -> CovarianceEstimate:
        # Cov giornaliera × periodi/anno
        # Assunzione: rendimenti i.i.d., quindi Var[r_ann] = Var[r_daily] × N
        # e Cov[r_i_ann, r_j_ann] = Cov[r_i_daily, r_j_daily] × N
        cov_daily = returns.cov().values
        cov = cov_daily * ann_factor
        cond = _condition_number(cov)

        logger.info(f"SampleCovariance: ann_factor={ann_factor}, "
                    f"condition_number={cond:.1f}")
        return CovarianceEstimate(
            cov=cov,
            tickers=list(returns.columns),
            method=self.name,
            shrinkage_intensity=0.0,
            ann_factor=ann_factor,
            condition_number=cond,
        )


class LedoitWolfCovariance(CovarianceEstimator):
    """Stimatore Ledoit-Wolf (shrinkage verso matrice diagonale a varianza costante).

    Usa l'implementazione di scikit-learn.
    """

    @property
    def name(self) -> str:
        return "ledoit_wolf"

    def estimate(self, returns: pd.DataFrame, ann_factor: int) -> CovarianceEstimate:
        lw = LedoitWolf()
        lw.fit(returns.values)

        cov_daily = lw.covariance_
        alpha = lw.shrinkage_
        cov = cov_daily * ann_factor
        cond = _condition_number(cov)

        logger.info(f"LedoitWolf: shrinkage_intensity={alpha:.4f}, "
                    f"condition_number={cond:.1f}, ann_factor={ann_factor}")
        return CovarianceEstimate(
            cov=cov,
            tickers=list(returns.columns),
            method=self.name,
            shrinkage_intensity=float(alpha),
            ann_factor=ann_factor,
            condition_number=cond,
        )


class OASCovariance(CovarianceEstimator):
    """Oracle Approximating Shrinkage (OAS).

    Variante del Ledoit-Wolf con formula analitica che approssima
    l'oracolo ottimale. Usa l'implementazione di scikit-learn.
    """

    @property
    def name(self) -> str:
        return "oas"

    def estimate(self, returns: pd.DataFrame, ann_factor: int) -> CovarianceEstimate:
        oas = OAS()
        oas.fit(returns.values)

        cov_daily = oas.covariance_
        alpha = oas.shrinkage_
        cov = cov_daily * ann_factor
        cond = _condition_number(cov)

        logger.info(f"OAS: shrinkage_intensity={alpha:.4f}, "
                    f"condition_number={cond:.1f}, ann_factor={ann_factor}")
        return CovarianceEstimate(
            cov=cov,
            tickers=list(returns.columns),
            method=self.name,
            shrinkage_intensity=float(alpha),
            ann_factor=ann_factor,
            condition_number=cond,
        )


# --- Registry per selezione da configurazione ---
COV_ESTIMATORS: dict[str, type[CovarianceEstimator]] = {
    "sample": SampleCovariance,
    "ledoit_wolf": LedoitWolfCovariance,
    "oas": OASCovariance,
}


def get_cov_estimator(name: str) -> CovarianceEstimator:
    """Restituisce un'istanza dello stimatore di covarianza per nome.

    Nomi disponibili: sample, ledoit_wolf, oas
    """
    if name not in COV_ESTIMATORS:
        raise ValueError(
            f"Stimatore di covarianza '{name}' non trovato. "
            f"Disponibili: {list(COV_ESTIMATORS.keys())}"
        )
    return COV_ESTIMATORS[name]()
