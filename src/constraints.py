"""
Definizione dei vincoli di portafoglio.

I vincoli vengono espressi come oggetti Python e poi tradotti
in vincoli CVXPY dal motore di ottimizzazione.
"""

from dataclasses import dataclass, field


@dataclass
class PortfolioConstraints:
    """Insieme di vincoli per l'ottimizzazione di portafoglio.

    Attributi:
        long_only: se True, tutti i pesi >= 0 (no short selling)
        fully_invested: se True, somma pesi = 1; se False, somma pesi <= 1
                        (la differenza da 1 è liquidità)
        min_weight: peso minimo per singolo asset (es. 0.0 o 0.01)
        max_weight: peso massimo per singolo asset (es. 0.20 per max 20%)
        group_constraints: vincoli per gruppo/asset class
            dict con chiave = nome gruppo (es. "crypto"),
            valore = (min_pct, max_pct) come frazioni (es. (0.0, 0.15))
        return_floor: rendimento atteso annualizzato minimo del portafoglio
                      (mu^T w >= return_floor). None = nessun vincolo.
        risk_ceiling: volatilità annualizzata massima del portafoglio. None = nessuno.
        target_return: rendimento target per ottimizzazione min-rischio. None = nessuno.
    """
    long_only: bool = True
    fully_invested: bool = True
    min_weight: float = 0.0
    max_weight: float = 1.0
    group_constraints: dict[str, tuple[float, float]] = field(default_factory=dict)
    return_floor: float | None = None
    risk_ceiling: float | None = None
    target_return: float | None = None


# Preset di vincoli comuni
UNCONSTRAINED = PortfolioConstraints(
    long_only=False,
    fully_invested=True,
    min_weight=-1.0,
    max_weight=1.0,
)

LONG_ONLY_DEFAULT = PortfolioConstraints(
    long_only=True,
    fully_invested=True,
    min_weight=0.0,
    max_weight=1.0,
)
