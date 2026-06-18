"""
Layer pratici: costi reali, fiscalita', FX e transizione (Fase 8).

Quattro sotto-moduli indipendenti che avvolgono le fasi 1-7:

8.1 — Costi reali: TER drag, spread per classe, commissioni broker
8.2 — Fiscalita' italiana indicativa: capital gain, bollo, asimmetria ETF
8.3 — Gestione cambio: separazione rendimento strumento vs effetto FX
8.4 — Integrazione portafoglio esistente: piano di transizione

TUTTI i parametri (aliquote, spread, commissioni) vengono dal file
config/costs_tax.yaml. Nessun numero hardcoded in questo modulo.

Ogni risultato "al netto" e' sempre accompagnato dal "lordo",
con etichetta "stima indicativa".

NOTA SULLA SCALA: i costi assoluti (minimo commissione broker in EUR)
richiedono un capitale di riferimento in EUR. Le equity curve del motore
usano un nozionale di default = 100, quindi build_cost_breakdown e
build_tax_breakdown accettano un parametro capital_eur (default 100_000)
per scalare correttamente le fee assolute.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from .universe import load_universe

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "config" / "costs_tax.yaml"
ANN_FACTOR = 252

# Capitale di riferimento di default per i costi assoluti (EUR).
# Le equity curve del motore partono da 100 nozionali; le fee assolute
# (es. minimo commissione 1.50 EUR) vanno applicate su un capitale reale.
DEFAULT_CAPITAL_EUR = 100_000


# ============================================================
# Caricamento configurazione
# ============================================================

def load_costs_config(path: Path | None = None) -> dict:
    """Carica la configurazione costi/tasse da YAML."""
    path = path or DEFAULT_CONFIG_PATH
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ============================================================
# Helper: CAGR sicuro (anti-NaN)
# ============================================================

def _safe_cagr(pv_final: float, pv_initial: float, n_days: int,
               ann_factor: int = ANN_FACTOR) -> float:
    """Calcola il CAGR con guardia anti-NaN.

    Se il valore finale e' <= 0 (costi che superano il capitale),
    logga un WARNING e restituisce -1.0 (= -100%) invece di NaN.
    """
    if n_days <= 0 or pv_initial <= 0:
        return 0.0
    if pv_final <= 0:
        logger.warning(
            "Valore netto del portafoglio <= 0 (%.2f): costi superiori al capitale. "
            "Verificare che il capitale di riferimento (capital_eur) sia realistico "
            "e non il nozionale 100 del motore. CAGR impostato a -100%%.",
            pv_final,
        )
        return -1.0
    return (pv_final / pv_initial) ** (ann_factor / n_days) - 1


# ============================================================
# 8.1 — Costi reali e loro impatto
# ============================================================

@dataclass
class CostBreakdown:
    """Riepilogo costi per un backtest o una transizione.

    Tutti i campi 'netto' sono stime indicative.
    """
    # TER
    ter_drag_annual: float          # TER medio ponderato annuo (%)
    ter_drag_total: float           # TER pagato nel periodo (unita' di portafoglio)

    # Transazione
    spread_total: float             # Spread totale pagato
    commission_total: float         # Commissioni broker totali
    tx_cost_total: float            # spread + commissioni

    # Riepilogo
    total_costs: float              # TER drag + tx costs
    cagr_gross: float               # CAGR lordo (senza costi)
    cagr_net_costs: float           # CAGR netto costi (stima indicativa)
    cost_impact_cagr: float         # Differenza in punti di CAGR

    # Capitale di riferimento usato per i costi assoluti
    capital_eur: float = DEFAULT_CAPITAL_EUR

    # Flag: True se i costi hanno superato il capitale (risultato degradato)
    costs_exceed_capital: bool = False


def compute_weighted_ter(weights: dict[str, float],
                         universe: pd.DataFrame | None = None) -> float:
    """Calcola il TER medio ponderato per un portafoglio."""
    if universe is None:
        universe = load_universe()
    total = 0.0
    for ticker, w in weights.items():
        if ticker in universe.index:
            ter_pct = universe.loc[ticker, "ter"]
            total += abs(w) * (ter_pct / 100.0)
    return total


def compute_tx_cost_for_trade(
    turnover_by_ticker: dict[str, float],
    portfolio_value: float,
    asset_class_map: dict[str, str],
    config: dict | None = None,
) -> tuple[float, float]:
    """Calcola spread + commissione per un singolo ribilanciamento.

    Parametri:
        turnover_by_ticker: {ticker: |delta_weight|} per ogni strumento scambiato
        portfolio_value: controvalore del portafoglio IN EUR
        asset_class_map: ticker -> asset class
        config: configurazione costi (da load_costs_config())

    Restituisce:
        (spread_cost, commission_cost) in EUR
    """
    if config is None:
        config = load_costs_config()
    tc = config["transaction_costs"]
    spread_bps = tc["spread_bps"]
    broker_pct = tc["broker_commission_pct"] / 100.0
    broker_min = tc["broker_minimum_eur"]

    spread_cost = 0.0
    commission_cost = 0.0

    for ticker, delta_w in turnover_by_ticker.items():
        if abs(delta_w) < 1e-10:
            continue
        trade_value = abs(delta_w) * portfolio_value
        ac = asset_class_map.get(ticker, "equity")
        sp_bps = spread_bps.get(ac, spread_bps.get("equity", 5))
        spread_cost += trade_value * sp_bps / 10_000

        comm = max(trade_value * broker_pct, broker_min)
        commission_cost += comm

    return spread_cost, commission_cost


def apply_ter_drag(
    portfolio_value: pd.Series,
    weights_history: pd.DataFrame,
    universe: pd.DataFrame | None = None,
) -> tuple[pd.Series, float]:
    """Applica il TER come drag giornaliero continuo alla equity curve.

    Il TER di ogni strumento e' scalato per il peso giornaliero.

    Restituisce:
        (portfolio_value_net_ter, ter_drag_total)
        dove ter_drag_total e' il costo totale in unita' di portafoglio iniziale.
    """
    if universe is None:
        universe = load_universe()

    ter_map = {}
    for ticker in weights_history.columns:
        if ticker in universe.index:
            ter_map[ticker] = universe.loc[ticker, "ter"] / 100.0
        else:
            ter_map[ticker] = 0.0

    daily_ter_rate = np.zeros(len(portfolio_value))
    for ticker in weights_history.columns:
        ter_annual = ter_map.get(ticker, 0.0)
        daily_ter_rate += weights_history[ticker].values * ter_annual / ANN_FACTOR

    # Applica il drag cumulativo
    pv_gross = portfolio_value.values.copy().astype(float)
    pv_net = pv_gross.copy()
    for t in range(1, len(pv_net)):
        ratio = pv_gross[t] / pv_gross[t - 1] if pv_gross[t - 1] > 0 else 1.0
        pv_net[t] = pv_net[t - 1] * ratio * (1 - daily_ter_rate[t])

    pv_net_series = pd.Series(pv_net, index=portfolio_value.index,
                              name="portfolio_value_net_ter")
    ter_total = float(pv_gross[-1] - pv_net[-1]) if len(pv_gross) > 0 else 0.0

    return pv_net_series, ter_total


def build_cost_breakdown(
    portfolio_value: pd.Series,
    weights_history: pd.DataFrame,
    rebalance_log: list,
    target_weights: dict[str, float],
    asset_class_map: dict[str, str],
    config: dict | None = None,
    universe: pd.DataFrame | None = None,
    capital_eur: float = DEFAULT_CAPITAL_EUR,
) -> CostBreakdown:
    """Costruisce il riepilogo costi completo per un backtest.

    Parametri:
        portfolio_value: equity curve (puo' essere nozionale, es. base 100)
        weights_history: pesi giornalieri
        rebalance_log: lista RebalanceEvent
        target_weights: pesi target del portafoglio
        asset_class_map: ticker -> asset class
        config: configurazione costi
        universe: DataFrame universo strumenti
        capital_eur: capitale di riferimento in EUR per i costi assoluti
                     (minimo commissione broker). Default: 100_000 EUR.
                     NON usare il nozionale 100 del motore.
    """
    if config is None:
        config = load_costs_config()
    if universe is None:
        universe = load_universe()

    # Fattore di scala: converte il nozionale dell'equity curve in EUR reali
    pv_initial = float(portfolio_value.iloc[0]) if len(portfolio_value) > 0 else 1.0
    scale = capital_eur / pv_initial if pv_initial > 0 else 1.0

    # TER drag (proporzionale, scala-invariante — calcolato sul nozionale)
    ter_annual = compute_weighted_ter(target_weights, universe)
    pv_net_ter, ter_total_noz = apply_ter_drag(portfolio_value, weights_history, universe)
    ter_total = ter_total_noz * scale  # In EUR

    # Costi di transazione per ribilanciamento (su scala EUR reale)
    spread_total = 0.0
    commission_total = 0.0
    for event in rebalance_log:
        turnover_by_ticker = {}
        for ticker in set(list(event.weights_before.keys()) +
                         list(event.weights_after.keys())):
            w_before = event.weights_before.get(ticker, 0.0)
            w_after = event.weights_after.get(ticker, 0.0)
            turnover_by_ticker[ticker] = abs(w_after - w_before)

        # Valore del portafoglio in EUR alla data dell'evento
        pv_at_date_noz = float(portfolio_value.iloc[0])
        event_date = pd.Timestamp(event.date)
        if event_date in portfolio_value.index:
            pv_at_date_noz = float(portfolio_value.loc[event_date])
        elif len(portfolio_value) > 0:
            idx = portfolio_value.index.get_indexer([event_date], method="nearest")
            if idx[0] >= 0:
                pv_at_date_noz = float(portfolio_value.iloc[idx[0]])

        pv_at_date_eur = pv_at_date_noz * scale

        sp, comm = compute_tx_cost_for_trade(
            turnover_by_ticker, pv_at_date_eur, asset_class_map, config,
        )
        spread_total += sp
        commission_total += comm

    tx_total = spread_total + commission_total
    total_costs = ter_total + tx_total

    # CAGR lordo (scala-invariante)
    pv = portfolio_value.dropna()
    n_days = len(pv) - 1
    cagr_gross = _safe_cagr(float(pv.iloc[-1]), float(pv.iloc[0]), n_days)

    # CAGR netto: calcola sul nozionale poi applica impatto tx in percentuale
    pv_net = pv_net_ter.dropna()
    costs_exceed = False
    if n_days > 0 and len(pv_net) > 1 and pv_net.iloc[0] > 0:
        pv_final_eur = float(pv.iloc[-1]) * scale
        tx_impact_ratio = tx_total / pv_final_eur if pv_final_eur > 0 else 0.0
        pv_final_net_noz = float(pv_net.iloc[-1]) * (1 - tx_impact_ratio)
        if pv_final_net_noz <= 0:
            costs_exceed = True
        cagr_net = _safe_cagr(pv_final_net_noz, float(pv_net.iloc[0]), n_days)
    else:
        cagr_net = 0.0

    return CostBreakdown(
        ter_drag_annual=ter_annual,
        ter_drag_total=ter_total,
        spread_total=spread_total,
        commission_total=commission_total,
        tx_cost_total=tx_total,
        total_costs=total_costs,
        cagr_gross=cagr_gross,
        cagr_net_costs=cagr_net,
        cost_impact_cagr=cagr_gross - cagr_net,
        capital_eur=capital_eur,
        costs_exceed_capital=costs_exceed,
    )


# ============================================================
# 8.2 — Fiscalita' italiana (INDICATIVA)
# ============================================================

@dataclass
class TaxBreakdown:
    """Stima INDICATIVA dell'impatto fiscale italiano.

    ATTENZIONE: questi numeri sono stime indicative.
    NON costituiscono consulenza fiscale. Verificare con un professionista.
    """
    # Capital gain
    capital_gain_tax: float         # Imposta su plusvalenze realizzate
    capital_gain_rate_effective: float  # Aliquota effettiva media

    # Bollo
    bollo_annual: float             # Bollo annuo stimato
    bollo_total: float              # Bollo totale nel periodo

    # Totale
    total_tax: float                # Capital gain + bollo
    cagr_gross: float
    cagr_net_costs: float           # Netto soli costi (da CostBreakdown)
    cagr_net_tax: float             # Netto costi + tasse (stima indicativa)
    tax_impact_cagr: float          # Impatto tasse in punti di CAGR

    # Capitale di riferimento
    capital_eur: float = DEFAULT_CAPITAL_EUR

    # Note
    notes: list[str] = field(default_factory=list)


def _effective_tax_rate(
    asset_class: str,
    config: dict,
) -> float:
    """Calcola l'aliquota effettiva per una classe di attivo.

    Per i bond, miscela l'aliquota agevolata (12.5%) con quella ordinaria (26%)
    in base alla quota governativa configurata.
    """
    tax_cfg = config["tax"]
    cg_rate = tax_cfg["capital_gain_rate"]
    govt_rate = tax_cfg["govt_bond_rate"]
    govt_quota = tax_cfg["govt_quota_by_class"].get(asset_class, 0.0)

    if asset_class == "crypto":
        return tax_cfg["crypto_rate"]

    if govt_quota > 0:
        return govt_quota * govt_rate + (1 - govt_quota) * cg_rate

    return cg_rate


def compute_capital_gain_tax(
    rebalance_log: list,
    portfolio_value: pd.Series,
    asset_class_map: dict[str, str],
    config: dict | None = None,
    capital_eur: float = DEFAULT_CAPITAL_EUR,
) -> float:
    """Stima INDICATIVA dell'imposta sui capital gain realizzati.

    Il modello assume che ogni vendita (riduzione di peso) realizzi un gain
    proporzionale al rendimento accumulato fino a quel punto.
    Le plusvalenze da ETF armonizzati NON sono compensabili con minusvalenze
    pregresse (asimmetria redditi di capitale / redditi diversi).

    Tassazione alla REALIZZAZIONE: si tassa solo quando si vende.
    Un buy & hold differisce l'imposta (vantaggio fiscale).

    Il capital_eur scala l'equity curve nozionale in EUR reali.
    """
    if config is None:
        config = load_costs_config()

    pv = portfolio_value
    pv_initial = float(pv.iloc[0]) if len(pv) > 0 else 1.0
    scale = capital_eur / pv_initial if pv_initial > 0 else 1.0

    tax_total = 0.0

    for event in rebalance_log:
        event_date = pd.Timestamp(event.date)
        if event_date in pv.index:
            current_pv = float(pv.loc[event_date])
        elif len(pv) > 0:
            idx = pv.index.get_indexer([event_date], method="nearest")
            current_pv = float(pv.iloc[idx[0]]) if idx[0] >= 0 else float(pv.iloc[0])
        else:
            continue

        initial_pv = float(pv.iloc[0])
        gain_ratio = (current_pv / initial_pv - 1) if initial_pv > 0 else 0.0

        if gain_ratio <= 0:
            continue

        current_pv_eur = current_pv * scale

        for ticker in set(list(event.weights_before.keys()) +
                         list(event.weights_after.keys())):
            w_before = event.weights_before.get(ticker, 0.0)
            w_after = event.weights_after.get(ticker, 0.0)
            delta = w_before - w_after

            if delta <= 0:
                continue

            ac = asset_class_map.get(ticker, "equity")
            rate = _effective_tax_rate(ac, config)
            taxable_gain = delta * current_pv_eur * gain_ratio
            tax_total += taxable_gain * rate

    return tax_total


def compute_bollo(
    portfolio_value: pd.Series,
    config: dict | None = None,
    capital_eur: float = DEFAULT_CAPITAL_EUR,
) -> tuple[float, float]:
    """Calcola il bollo titoli (imposta di bollo sul deposito).

    Restituisce (bollo_annuo_medio, bollo_totale_periodo) in EUR.
    Il bollo e' proporzionale al controvalore medio del deposito.
    """
    if config is None:
        config = load_costs_config()

    bollo_rate = config["tax"]["bollo_rate"]
    pv = portfolio_value.dropna()

    if len(pv) < 2:
        return 0.0, 0.0

    pv_initial = float(pv.iloc[0])
    scale = capital_eur / pv_initial if pv_initial > 0 else 1.0

    avg_value_eur = float(pv.mean()) * scale
    bollo_annual = avg_value_eur * bollo_rate

    n_days = len(pv) - 1
    years = n_days / ANN_FACTOR
    bollo_total = bollo_annual * years

    return bollo_annual, bollo_total


def build_tax_breakdown(
    portfolio_value: pd.Series,
    rebalance_log: list,
    asset_class_map: dict[str, str],
    cost_breakdown: CostBreakdown | None = None,
    config: dict | None = None,
    capital_eur: float = DEFAULT_CAPITAL_EUR,
) -> TaxBreakdown:
    """Costruisce la stima INDICATIVA dell'impatto fiscale.

    Parametri:
        capital_eur: capitale di riferimento in EUR per scalare le tasse.
                     Default: 100_000 EUR. NON usare il nozionale 100.

    Il risultato e' una stima indicativa, NON consulenza fiscale.
    """
    if config is None:
        config = load_costs_config()

    # Capital gain (su scala EUR)
    cg_tax = compute_capital_gain_tax(
        rebalance_log, portfolio_value, asset_class_map, config,
        capital_eur=capital_eur,
    )

    # Aliquota effettiva media
    total_sold = 0.0
    weighted_rate = 0.0
    for event in rebalance_log:
        for ticker in event.weights_before:
            delta = event.weights_before.get(ticker, 0.0) - event.weights_after.get(ticker, 0.0)
            if delta > 0:
                ac = asset_class_map.get(ticker, "equity")
                rate = _effective_tax_rate(ac, config)
                weighted_rate += delta * rate
                total_sold += delta
    eff_rate = weighted_rate / total_sold if total_sold > 0 else config["tax"]["capital_gain_rate"]

    # Bollo (su scala EUR)
    bollo_annual, bollo_total = compute_bollo(portfolio_value, config,
                                              capital_eur=capital_eur)

    total_tax = cg_tax + bollo_total

    # CAGR (scala-invariante)
    pv = portfolio_value.dropna()
    n_days = len(pv) - 1
    cagr_gross = _safe_cagr(float(pv.iloc[-1]), float(pv.iloc[0]), n_days)

    cagr_net_costs = cost_breakdown.cagr_net_costs if cost_breakdown else cagr_gross

    # CAGR netto tasse: impatto percentuale su equity curve
    pv_final_eur = float(pv.iloc[-1]) * (capital_eur / float(pv.iloc[0])
                                          if len(pv) > 0 and pv.iloc[0] > 0 else 1.0)
    total_cost_eur = (cost_breakdown.total_costs if cost_breakdown else 0.0) + total_tax

    if n_days > 0 and pv_final_eur > 0 and float(pv.iloc[0]) > 0:
        net_ratio = 1 - total_cost_eur / pv_final_eur
        pv_final_net_noz = float(pv.iloc[-1]) * max(net_ratio, 0.0)
        cagr_net_tax = _safe_cagr(pv_final_net_noz, float(pv.iloc[0]), n_days)
    else:
        cagr_net_tax = 0.0

    notes = [
        "Stima INDICATIVA, NON consulenza fiscale.",
        "Le plusvalenze da ETF armonizzati sono 'redditi di capitale' e NON "
        "compensabili con minusvalenze pregresse ('redditi diversi').",
    ]
    if any(asset_class_map.get(t, "") == "crypto" for t in asset_class_map):
        notes.append(
            "La tassazione cripto in Italia e' in evoluzione. "
            "L'aliquota usata e' indicativa: verificare per l'anno corrente."
        )

    return TaxBreakdown(
        capital_gain_tax=cg_tax,
        capital_gain_rate_effective=eff_rate,
        bollo_annual=bollo_annual,
        bollo_total=bollo_total,
        total_tax=total_tax,
        cagr_gross=cagr_gross,
        cagr_net_costs=cagr_net_costs,
        cagr_net_tax=cagr_net_tax,
        tax_impact_cagr=cagr_net_costs - cagr_net_tax,
        capital_eur=capital_eur,
        notes=notes,
    )


# ============================================================
# 8.3 — Gestione cambio (FX)
# ============================================================

@dataclass
class FxImpact:
    """Separazione rendimento strumento vs effetto cambio."""
    ticker: str
    currency: str
    total_return_eur: float         # Rendimento totale in EUR
    instrument_return_local: float  # Rendimento dello strumento in valuta locale
    fx_return: float                # Effetto cambio (EUR vs valuta locale)
    note: str = ""


def compute_fx_impact(
    prices_eur: pd.Series,
    prices_local: pd.Series | None,
    fx_rate: pd.Series | None,
    ticker: str,
    currency: str,
    base: str = "EUR",
) -> FxImpact:
    """Calcola la separazione rendimento strumento vs effetto FX.

    Per strumenti gia' in EUR, l'effetto cambio e' nullo.
    Per strumenti in valuta estera, separa le due componenti.
    """
    prices_e = prices_eur.dropna()
    if len(prices_e) < 2:
        return FxImpact(
            ticker=ticker, currency=currency,
            total_return_eur=0.0, instrument_return_local=0.0,
            fx_return=0.0, note="Dati insufficienti",
        )

    total_return_eur = float(prices_e.iloc[-1] / prices_e.iloc[0] - 1)

    if currency == base:
        return FxImpact(
            ticker=ticker, currency=currency,
            total_return_eur=total_return_eur,
            instrument_return_local=total_return_eur,
            fx_return=0.0,
            note="Strumento gia' quotato in EUR, effetto cambio nullo.",
        )

    # Strumento in valuta estera
    if prices_local is not None and len(prices_local.dropna()) >= 2:
        pl = prices_local.dropna()
        instrument_return_local = float(pl.iloc[-1] / pl.iloc[0] - 1)
    else:
        instrument_return_local = total_return_eur  # Fallback

    if fx_rate is not None and len(fx_rate.dropna()) >= 2:
        fx = fx_rate.dropna()
        fx_return = float(fx.iloc[-1] / fx.iloc[0] - 1)
    else:
        # Ricava l'effetto cambio dalla decomposizione:
        # (1 + r_eur) = (1 + r_local) * (1 + r_fx)
        fx_return = (1 + total_return_eur) / (1 + instrument_return_local) - 1 \
            if abs(1 + instrument_return_local) > 1e-10 else 0.0

    return FxImpact(
        ticker=ticker, currency=currency,
        total_return_eur=total_return_eur,
        instrument_return_local=instrument_return_local,
        fx_return=fx_return,
        note=(f"Rischio cambio {currency}/{base} presente e NON coperto (no hedging)."
              if currency != base else ""),
    )


def check_universe_fx(universe: pd.DataFrame | None = None,
                      base: str = "EUR") -> list[FxImpact]:
    """Verifica l'esposizione cambio dell'universo corrente.

    Per l'universo attuale (tutto quotato in EUR), conferma che
    l'effetto cambio e' nullo su tutti gli strumenti.
    """
    if universe is None:
        universe = load_universe()

    results = []
    for ticker, row in universe.iterrows():
        ccy = row["currency"]
        impact = FxImpact(
            ticker=ticker,
            currency=ccy,
            total_return_eur=0.0,
            instrument_return_local=0.0,
            fx_return=0.0,
            note=("Strumento gia' quotato in EUR, effetto cambio nullo."
                  if ccy == base
                  else f"Rischio cambio {ccy}/{base} presente e NON coperto (no hedging)."),
        )
        results.append(impact)
    return results


# ============================================================
# 8.4 — Integrazione con portafoglio esistente
# ============================================================

@dataclass
class TransitionOrder:
    """Singolo ordine di acquisto o vendita."""
    ticker: str
    action: str             # "buy" o "sell"
    weight_delta: float     # Variazione peso (positivo = acquisto)
    amount_eur: float       # Importo in EUR
    asset_class: str


@dataclass
class TransitionPlan:
    """Piano di transizione da portafoglio attuale a target.

    Tutti i costi e le tasse sono stime indicative.
    """
    orders: list[TransitionOrder]
    turnover: float                 # Turnover totale (somma |delta_w|)

    # Costi di transizione
    spread_cost: float
    commission_cost: float
    tx_cost_total: float            # spread + commissioni

    # Impatto fiscale della transizione (stima indicativa)
    capital_gain_tax: float         # Imposta sui realizzi
    total_transition_cost: float    # tx_cost + tasse

    # Pesi risultanti
    weights_after: dict[str, float]

    # Metadati
    capital: float
    notes: list[str] = field(default_factory=list)


def build_transition_plan(
    current_holdings: dict[str, float],
    target_weights: dict[str, float],
    capital: float,
    asset_class_map: dict[str, str],
    cost_basis: dict[str, float] | None = None,
    config: dict | None = None,
) -> TransitionPlan:
    """Calcola il piano di transizione da portafoglio attuale a target.

    Parametri:
        current_holdings: {ticker: controvalore_eur} portafoglio attuale
        target_weights: {ticker: peso_target} dalla Fase 4 o core-satellite
        capital: capitale totale del portafoglio (somma current_holdings) IN EUR
        asset_class_map: ticker -> asset class
        cost_basis: {ticker: prezzo_medio_carico} per calcolo capital gain.
                    Se None, assume carico = valore attuale (nessun gain).
        config: configurazione costi/tasse

    Restituisce:
        TransitionPlan con lista ordini, costi e tasse.
    """
    if config is None:
        config = load_costs_config()

    if capital <= 0:
        return TransitionPlan(
            orders=[], turnover=0.0,
            spread_cost=0.0, commission_cost=0.0, tx_cost_total=0.0,
            capital_gain_tax=0.0, total_transition_cost=0.0,
            weights_after={}, capital=capital,
            notes=["Capitale nullo o negativo."],
        )

    # Calcola pesi attuali
    current_weights = {t: v / capital for t, v in current_holdings.items()}

    # Tutti i ticker coinvolti
    all_tickers = sorted(set(list(current_weights.keys()) + list(target_weights.keys())))

    orders: list[TransitionOrder] = []
    turnover_by_ticker: dict[str, float] = {}
    turnover = 0.0
    cg_tax = 0.0

    for ticker in all_tickers:
        w_current = current_weights.get(ticker, 0.0)
        w_target = target_weights.get(ticker, 0.0)
        delta = w_target - w_current

        if abs(delta) < 1e-8:
            continue

        ac = asset_class_map.get(ticker, "equity")
        amount = delta * capital
        action = "buy" if delta > 0 else "sell"

        orders.append(TransitionOrder(
            ticker=ticker, action=action,
            weight_delta=delta, amount_eur=amount,
            asset_class=ac,
        ))

        turnover_by_ticker[ticker] = abs(delta)
        turnover += abs(delta)

        # Capital gain tax su vendite
        if delta < 0 and cost_basis is not None:
            current_value = current_holdings.get(ticker, 0.0)
            cost = cost_basis.get(ticker, current_value)
            gain = current_value - cost
            if gain > 0:
                sell_fraction = abs(delta) * capital / current_value \
                    if current_value > 0 else 0.0
                sell_fraction = min(sell_fraction, 1.0)
                realized_gain = gain * sell_fraction
                rate = _effective_tax_rate(ac, config)
                cg_tax += realized_gain * rate

    # Costi di transazione
    spread_cost, commission_cost = compute_tx_cost_for_trade(
        turnover_by_ticker, capital, asset_class_map, config,
    )
    tx_total = spread_cost + commission_cost
    total_cost = tx_total + cg_tax

    # Pesi risultanti (= target)
    weights_after = {t: target_weights.get(t, 0.0) for t in all_tickers
                     if target_weights.get(t, 0.0) > 1e-8}

    notes = ["Stima indicativa dei costi di transizione."]
    if cg_tax > 0:
        notes.append(
            "L'imposta sui capital gain si applica solo alle plusvalenze "
            "realizzate con la vendita. Conviene valutare se vendere tutto "
            "o mantenere posizioni in guadagno."
        )
    if any(asset_class_map.get(t, "") == "crypto" for t in all_tickers):
        notes.append(
            "La tassazione cripto in Italia e' in evoluzione. "
            "Verificare l'aliquota per l'anno corrente."
        )

    return TransitionPlan(
        orders=orders,
        turnover=turnover,
        spread_cost=spread_cost,
        commission_cost=commission_cost,
        tx_cost_total=tx_total,
        capital_gain_tax=cg_tax,
        total_transition_cost=total_cost,
        weights_after=weights_after,
        capital=capital,
        notes=notes,
    )
