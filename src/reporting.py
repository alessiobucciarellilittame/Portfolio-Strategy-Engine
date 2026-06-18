"""
Reportistica e piano nel tempo (Fase 7).

Produce un "piano d'investimento" PDF leggibile da un investitore non tecnico.
Separa la costruzione del contenuto (StrategyReport) dall'impaginazione (PDF).

La generazione del contenuto CONSUMA gli output delle fasi precedenti
(ProfileResult, CoreSatelliteResult, StrategyResult, WalkForwardResult)
senza ricalcoli: i numeri vengono direttamente dagli oggetti del motore.

OUTPUT (contratto):
    StrategyReport con:
    - profile: info profilo (nome, descrizione, orizzonte, vol ceiling)
    - allocation: pesi per strumento con metadati (nome, classe, regione, TER)
    - class_allocation: pesi aggregati per classe di attivo
    - stats: statistiche attese (rendimento, vol, sharpe, cvar)
    - backtest: metriche dal backtest (CAGR, max_dd, sharpe realizzato)
    - equity_curve: serie equity curve (se disponibile)
    - rebalance_schedule: frequenza e regole di ribilanciamento
    - satellite: info satellite cripto (se presente)
    - disclaimer: testi di avvertimento
"""

import logging
import io
import base64
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from .profiles import ProfileResult, ProfileConfig, PROFILE_ORDER
from .optimizer import PortfolioResult
from .strategies import StrategyResult
from .universe import load_universe

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path(__file__).parent.parent / "output"


# ============================================================
# Contratto: StrategyReport
# ============================================================

@dataclass
class InstrumentAllocation:
    """Allocazione per singolo strumento con metadati."""
    ticker: str
    weight: float
    name: str
    asset_class: str
    region: str
    currency: str
    ter: float
    is_satellite: bool = False


@dataclass
class StrategyReport:
    """Contratto di output della Fase 7.

    Raccoglie in modo strutturato TUTTO cio' che va nel PDF.
    Il renderer PDF prende QUESTO oggetto.
    """
    # Profilo
    profile_name: str
    profile_description: str
    horizon_years: int
    horizon_band: str
    vol_ceiling: float | None
    effective_vol_ceiling: float | None
    generation_date: str

    # Allocazione
    allocation: list[InstrumentAllocation]
    class_allocation: dict[str, float]  # classe -> peso totale

    # Statistiche attese (dal motore)
    expected_return: float
    expected_volatility: float
    expected_sharpe: float
    expected_cvar_95: float
    risk_free_rate: float
    estimation_window: str  # es. "2015-01-02 / 2024-12-31"

    # Backtest (opzionale)
    backtest_cagr: float | None = None
    backtest_volatility: float | None = None
    backtest_max_drawdown: float | None = None
    backtest_sharpe: float | None = None
    backtest_n_rebalances: int | None = None
    backtest_total_costs: float | None = None
    backtest_period: str | None = None
    equity_curve: pd.Series | None = None

    # Satellite cripto
    satellite_weight: float = 0.0
    satellite_tickers: dict[str, float] = field(default_factory=dict)

    # Piano nel tempo
    rebalance_frequency: str = "quarterly"
    rebalance_rules: list[str] = field(default_factory=list)

    # Disclaimer
    disclaimers: list[str] = field(default_factory=list)

    # Validazione
    validation_issues: list[str] = field(default_factory=list)
    is_feasible: bool = True


@dataclass
class ComparisonReport:
    """Report di confronto multi-profilo."""
    profiles: list[StrategyReport]
    generation_date: str
    equity_curves: dict[str, pd.Series] = field(default_factory=dict)


# ============================================================
# Costruzione del report da oggetti del motore
# ============================================================

DISCLAIMER_TEXTS = [
    "Questo documento non costituisce consulenza finanziaria personalizzata "
    "ai sensi della normativa vigente (MiFID II / Consob).",
    "I rendimenti attesi e le statistiche di rischio sono STIME basate su dati "
    "storici e modelli statistici. Non rappresentano garanzie di performance futura.",
    "Le performance passate non sono indicative dei risultati futuri. "
    "Il valore dell'investimento puo' diminuire.",
    "Le stime di volatilita', CVaR e Sharpe ratio dipendono dalla finestra "
    "temporale e dai metodi di stima utilizzati.",
    "Prima di investire, consultare un consulente finanziario abilitato.",
]

REBALANCE_RULES = [
    "Verificare l'allocazione alla frequenza indicata.",
    "Ribilanciare se un singolo asset devia di oltre 5 punti percentuali dal target.",
    "Dopo un ribilanciamento, verificare che i costi di transazione siano ragionevoli.",
    "Rivalutare il profilo di rischio in caso di cambiamenti significativi "
    "nella situazione personale o nell'orizzonte temporale.",
]


def build_report(
    profile_result: ProfileResult,
    universe: pd.DataFrame | None = None,
    backtest_result: StrategyResult | None = None,
    core_satellite_result=None,
    rebalance_frequency: str = "quarterly",
) -> StrategyReport:
    """Costruisce un StrategyReport da un ProfileResult e oggetti opzionali.

    Tutti i numeri vengono DIRETTAMENTE dagli oggetti del motore, nessun ricalcolo.
    """
    if universe is None:
        universe = load_universe()

    pr = profile_result
    portfolio = pr.portfolio
    stats = portfolio.stats

    # --- Allocazione per strumento ---
    allocation = []
    class_totals: dict[str, float] = {}

    # Determina pesi e satellite
    satellite_weight = 0.0
    satellite_tickers: dict[str, float] = {}
    weights_to_use = portfolio.weights

    if core_satellite_result is not None:
        cs = core_satellite_result
        weights_to_use = cs.combined_weights
        satellite_weight = cs.crypto_weight_actual
        satellite_tickers = cs.satellite_weights
        # Usa stats combinate
        stats = cs.combined_stats

    for ticker, weight in sorted(weights_to_use.items(), key=lambda x: -x[1]):
        if abs(weight) < 1e-6:
            continue

        # Metadati dallo universe
        if ticker in universe.index:
            row = universe.loc[ticker]
            name = row["name"]
            asset_class = row["asset_class"]
            region = row["region"]
            currency = row["currency"]
            ter = row["ter"]
        else:
            name = ticker
            asset_class = "sconosciuto"
            region = "?"
            currency = "?"
            ter = 0.0

        is_sat = ticker in satellite_tickers

        allocation.append(InstrumentAllocation(
            ticker=ticker, weight=weight, name=name,
            asset_class=asset_class, region=region,
            currency=currency, ter=ter, is_satellite=is_sat,
        ))

        class_totals[asset_class] = class_totals.get(asset_class, 0.0) + weight

    # --- Finestra di stima ---
    metadata = pr.portfolio.metadata
    date_start = metadata.get("date_start", "?")
    date_end = metadata.get("date_end", "?")
    # Se core_satellite, prendi dal core result
    if core_satellite_result is not None:
        cm = core_satellite_result.profile_result.portfolio.metadata
        date_start = cm.get("date_start", date_start)
        date_end = cm.get("date_end", date_end)
    estimation_window = f"{date_start} / {date_end}"

    # --- Backtest ---
    bt_cagr = bt_vol = bt_mdd = bt_sharpe = None
    bt_n_reb = bt_costs = None
    bt_period = None
    equity_curve = None

    if backtest_result is not None:
        m = backtest_result.metrics
        bt_cagr = m.get("cagr")
        bt_vol = m.get("volatility")
        bt_mdd = m.get("max_drawdown")
        bt_sharpe = m.get("sharpe")
        bt_n_reb = int(m.get("n_rebalances", 0))
        bt_costs = m.get("total_costs")
        equity_curve = backtest_result.portfolio_value

        pv = backtest_result.portfolio_value
        if len(pv) >= 2:
            bt_period = f"{pv.index[0].date()} / {pv.index[-1].date()}"

    # --- Costruisci il report ---
    return StrategyReport(
        profile_name=pr.profile_name,
        profile_description=pr.profile_config.description,
        horizon_years=pr.horizon_years,
        horizon_band=pr.horizon_band,
        vol_ceiling=pr.profile_config.vol_ceiling,
        effective_vol_ceiling=pr.effective_vol_ceiling,
        generation_date=datetime.now().strftime("%Y-%m-%d %H:%M"),
        allocation=allocation,
        class_allocation=class_totals,
        expected_return=stats.get("expected_return", 0.0),
        expected_volatility=stats.get("volatility", 0.0),
        expected_sharpe=stats.get("sharpe_ratio", 0.0),
        expected_cvar_95=stats.get("cvar_95", 0.0),
        risk_free_rate=stats.get("risk_free_rate", 0.0),
        estimation_window=estimation_window,
        backtest_cagr=bt_cagr,
        backtest_volatility=bt_vol,
        backtest_max_drawdown=bt_mdd,
        backtest_sharpe=bt_sharpe,
        backtest_n_rebalances=bt_n_reb,
        backtest_total_costs=bt_costs,
        backtest_period=bt_period,
        equity_curve=equity_curve,
        satellite_weight=satellite_weight,
        satellite_tickers=satellite_tickers,
        rebalance_frequency=rebalance_frequency,
        rebalance_rules=list(REBALANCE_RULES),
        disclaimers=list(DISCLAIMER_TEXTS),
        validation_issues=list(pr.validation_issues),
        is_feasible=portfolio.is_feasible(),
    )


def build_comparison(
    reports: list[StrategyReport],
) -> ComparisonReport:
    """Costruisce un ComparisonReport da una lista di StrategyReport."""
    curves = {}
    for r in reports:
        if r.equity_curve is not None:
            curves[r.profile_name] = r.equity_curve

    return ComparisonReport(
        profiles=reports,
        generation_date=datetime.now().strftime("%Y-%m-%d %H:%M"),
        equity_curves=curves,
    )


# ============================================================
# Validazione del report
# ============================================================

def validate_report(report: StrategyReport) -> list[str]:
    """Verifica la coerenza del report con i dati sorgente."""
    issues = []

    # Pesi sommano a 1 (solo se feasible)
    if not report.is_feasible:
        return issues

    total = sum(a.weight for a in report.allocation)
    if abs(total - 1.0) > 1e-3:
        issues.append(f"Pesi non sommano a 1: {total:.6f}")

    # Nessun peso negativo
    for a in report.allocation:
        if a.weight < -1e-6:
            issues.append(f"Peso negativo: {a.ticker} = {a.weight:.6f}")

    # Class allocation coerente
    class_check: dict[str, float] = {}
    for a in report.allocation:
        class_check[a.asset_class] = class_check.get(a.asset_class, 0.0) + a.weight
    for cls, w in class_check.items():
        reported = report.class_allocation.get(cls, 0.0)
        if abs(w - reported) > 1e-4:
            issues.append(
                f"Classe '{cls}': calcolato {w:.4f} != riportato {reported:.4f}"
            )

    return issues


# ============================================================
# Generazione grafici (PNG in memoria)
# ============================================================

def _fig_to_base64(fig) -> str:
    """Converte un matplotlib Figure in stringa base64 PNG."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8")


def _chart_allocation(report: StrategyReport) -> str:
    """Grafico a barre dell'allocazione per classe."""
    classes = sorted(report.class_allocation.keys())
    weights = [report.class_allocation[c] * 100 for c in classes]

    colors_map = {
        "equity": "#4CAF50", "bond": "#2196F3",
        "commodity": "#FF9800", "crypto": "#9C27B0",
    }
    colors = [colors_map.get(c, "#607D8B") for c in classes]

    fig, ax = plt.subplots(figsize=(6, 3.5))
    bars = ax.barh(classes, weights, color=colors, edgecolor="white", height=0.6)
    for bar, w in zip(bars, weights):
        ax.text(bar.get_width() + 0.5, bar.get_y() + bar.get_height() / 2,
                f"{w:.1f}%", va="center", fontsize=9)
    ax.set_xlabel("Peso (%)")
    ax.set_title("Allocazione per classe di attivo")
    ax.set_xlim(0, max(weights) * 1.2 if weights else 100)
    ax.invert_yaxis()
    fig.tight_layout()
    return _fig_to_base64(fig)


def _chart_equity_curve(report: StrategyReport) -> str | None:
    """Grafico della equity curve."""
    if report.equity_curve is None or len(report.equity_curve) < 2:
        return None

    pv = report.equity_curve
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(7, 5),
                                    gridspec_kw={"height_ratios": [3, 1]},
                                    sharex=True)

    # Equity curve
    ax1.plot(pv.index, pv.values, color="#1976D2", linewidth=1)
    ax1.fill_between(pv.index, pv.values, alpha=0.1, color="#1976D2")
    ax1.set_ylabel("Valore portafoglio")
    ax1.set_title("Crescita simulata (backtest)")
    ax1.grid(True, alpha=0.3)

    # Drawdown
    cummax = pv.cummax()
    dd = (pv - cummax) / cummax * 100
    ax2.fill_between(pv.index, dd.values, 0, color="#F44336", alpha=0.4)
    ax2.set_ylabel("Drawdown (%)")
    ax2.set_xlabel("")
    ax2.grid(True, alpha=0.3)

    fig.tight_layout()
    return _fig_to_base64(fig)


def _chart_comparison_equity(comparison: ComparisonReport) -> str | None:
    """Grafico confronto equity curve dei 5 profili."""
    if not comparison.equity_curves:
        return None

    colors = {
        "conservativo": "#2196F3", "moderato": "#4CAF50",
        "bilanciato": "#FF9800", "dinamico": "#F44336",
        "aggressivo": "#9C27B0",
    }

    fig, ax = plt.subplots(figsize=(8, 4.5))
    for name in PROFILE_ORDER:
        if name in comparison.equity_curves:
            pv = comparison.equity_curves[name]
            # Normalizza a 100
            pv_norm = pv / pv.iloc[0] * 100
            ax.plot(pv_norm.index, pv_norm.values,
                    label=name.capitalize(), linewidth=1.2,
                    color=colors.get(name, "#607D8B"))

    ax.set_ylabel("Valore (base 100)")
    ax.set_title("Confronto equity curve per profilo")
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    return _fig_to_base64(fig)


# ============================================================
# Rendering HTML -> PDF
# ============================================================

def _check_weasyprint():
    """Verifica che weasyprint sia disponibile (incluse le librerie di sistema)."""
    try:
        import weasyprint  # noqa: F401
        return True
    except (ImportError, OSError):
        return False


def _pct(v: float | None, digits: int = 2) -> str:
    """Formatta un valore come percentuale."""
    if v is None:
        return "n/d"
    return f"{v * 100:.{digits}f}%"


def _render_profile_html(report: StrategyReport) -> str:
    """Genera l'HTML completo per un singolo profilo."""
    # Grafici
    alloc_chart = _chart_allocation(report)
    equity_chart = _chart_equity_curve(report)

    # Tabella allocazione per strumento
    rows_core = []
    rows_sat = []
    for a in report.allocation:
        row = (
            f"<tr><td>{a.ticker}</td><td>{a.name}</td>"
            f"<td>{a.asset_class}</td><td>{a.region}</td>"
            f"<td>{a.currency}</td><td>{a.ter:.2f}%</td>"
            f"<td class='num'>{_pct(a.weight, 1)}</td></tr>"
        )
        if a.is_satellite:
            rows_sat.append(row)
        else:
            rows_core.append(row)

    instrument_table = "\n".join(rows_core)

    satellite_section = ""
    if rows_sat:
        satellite_section = f"""
        <h3>Satellite cripto ({_pct(report.satellite_weight, 1)})</h3>
        <p>La quota cripto e' una scelta esplicita aggiunta sopra il core tradizionale.
           Non entra nell'ottimizzazione del core.</p>
        <table>
            <tr><th>Ticker</th><th>Strumento</th><th>Classe</th><th>Regione</th>
                <th>Valuta</th><th>TER</th><th>Peso</th></tr>
            {"".join(rows_sat)}
        </table>
        """

    # Backtest section
    backtest_section = ""
    if report.backtest_cagr is not None:
        backtest_section = f"""
        <h2>4. Crescita simulata (backtest)</h2>
        <p><em>Simulazione basata su prezzi storici reali nel periodo
           {report.backtest_period or 'n/d'}. Include costi di transazione.</em></p>
        <table class="stats">
            <tr><td>CAGR (rendimento annualizzato composto)</td>
                <td class="num">{_pct(report.backtest_cagr)}</td></tr>
            <tr><td>Volatilita' realizzata</td>
                <td class="num">{_pct(report.backtest_volatility)}</td></tr>
            <tr><td>Max drawdown</td>
                <td class="num">{_pct(report.backtest_max_drawdown)}</td></tr>
            <tr><td>Sharpe ratio realizzato</td>
                <td class="num">{f"{report.backtest_sharpe:.2f}" if report.backtest_sharpe is not None else "n/d"}</td></tr>
            <tr><td>Numero ribilanciamenti</td>
                <td class="num">{report.backtest_n_rebalances if report.backtest_n_rebalances is not None else 'n/d'}</td></tr>
            <tr><td>Costi totali di transazione</td>
                <td class="num">{f"{report.backtest_total_costs:.4f}" if report.backtest_total_costs is not None else "n/d"}</td></tr>
        </table>
        <p>In passato, in scenari simili, il portafoglio e' sceso fino a
           {_pct(report.backtest_max_drawdown)} dal suo massimo (max drawdown).</p>
        """
        if equity_chart:
            backtest_section += f"""
            <div class="chart">
                <img src="data:image/png;base64,{equity_chart}" />
            </div>
            """

    # Frequenza ribilanciamento
    freq_labels = {
        "monthly": "Mensile", "quarterly": "Trimestrale", "annual": "Annuale",
    }
    freq_label = freq_labels.get(report.rebalance_frequency,
                                  report.rebalance_frequency)

    # Piano nel tempo
    rules_html = "\n".join(f"<li>{r}</li>" for r in report.rebalance_rules)

    # Disclaimer
    disclaimers_html = "\n".join(f"<li>{d}</li>" for d in report.disclaimers)

    # Validazione
    validation_html = ""
    if report.validation_issues:
        items = "\n".join(f"<li>{v}</li>" for v in report.validation_issues)
        validation_html = f"""
        <div class="warning">
            <strong>Avvisi di validazione:</strong>
            <ul>{items}</ul>
        </div>
        """

    html = f"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="utf-8" />
<style>
    @page {{ size: A4; margin: 20mm 15mm; }}
    body {{ font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
           font-size: 10pt; color: #333; line-height: 1.4; }}
    h1 {{ color: #1565C0; border-bottom: 2px solid #1565C0; padding-bottom: 5px;
         font-size: 18pt; }}
    h2 {{ color: #1976D2; margin-top: 20px; font-size: 13pt;
         border-bottom: 1px solid #ddd; padding-bottom: 3px; }}
    h3 {{ color: #1E88E5; font-size: 11pt; }}
    table {{ border-collapse: collapse; width: 100%; margin: 10px 0; font-size: 9pt; }}
    th {{ background: #E3F2FD; padding: 6px 8px; text-align: left;
         border-bottom: 2px solid #90CAF9; }}
    td {{ padding: 5px 8px; border-bottom: 1px solid #eee; }}
    .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
    .stats td:first-child {{ width: 65%; }}
    .chart {{ text-align: center; margin: 15px 0; }}
    .chart img {{ max-width: 100%; }}
    .meta {{ color: #777; font-size: 8pt; }}
    .warning {{ background: #FFF3E0; border-left: 4px solid #FF9800;
               padding: 8px 12px; margin: 10px 0; font-size: 9pt; }}
    .disclaimer {{ background: #F5F5F5; padding: 10px 15px; margin-top: 20px;
                  font-size: 8pt; color: #666; border-radius: 4px; }}
    .disclaimer li {{ margin-bottom: 4px; }}
    .header-meta {{ display: flex; justify-content: space-between; }}
    .header-meta span {{ font-size: 9pt; color: #777; }}
</style>
</head>
<body>
    <h1>Piano d'investimento — {report.profile_name.capitalize()}</h1>

    <div class="header-meta">
        <span>Generato il {report.generation_date}</span>
        <span>Orizzonte: {report.horizon_years} anni ({report.horizon_band})</span>
    </div>

    {validation_html}

    <h2>1. Profilo investitore</h2>
    <table class="stats">
        <tr><td>Profilo</td><td>{report.profile_name.capitalize()}</td></tr>
        <tr><td>Descrizione</td><td>{report.profile_description}</td></tr>
        <tr><td>Orizzonte temporale</td><td>{report.horizon_years} anni (fascia: {report.horizon_band})</td></tr>
        <tr><td>Volatilita' target del core</td><td>{_pct(report.effective_vol_ceiling)}</td></tr>
    </table>

    <h2>2. Allocazione raccomandata</h2>

    <div class="chart">
        <img src="data:image/png;base64,{alloc_chart}" />
    </div>

    <h3>Core — asset tradizionali</h3>
    <table>
        <tr><th>Ticker</th><th>Strumento</th><th>Classe</th><th>Regione</th>
            <th>Valuta</th><th>TER</th><th>Peso</th></tr>
        {instrument_table}
    </table>

    {satellite_section}

    <h2>3. Attese di rischio e rendimento</h2>
    <p><em>Stime annualizzate basate su dati storici ({report.estimation_window}).
       NON sono garanzie di performance futura.</em></p>
    <table class="stats">
        <tr><td>Rendimento atteso annualizzato</td>
            <td class="num">{_pct(report.expected_return)}</td></tr>
        <tr><td>Volatilita' attesa annualizzata</td>
            <td class="num">{_pct(report.expected_volatility)}</td></tr>
        <tr><td>Sharpe ratio atteso</td>
            <td class="num">{report.expected_sharpe:.2f}</td></tr>
        <tr><td>CVaR 95% (perdita attesa nei casi peggiori)</td>
            <td class="num">{_pct(report.expected_cvar_95)}</td></tr>
        <tr><td>Tasso risk-free utilizzato</td>
            <td class="num">{_pct(report.risk_free_rate)}</td></tr>
    </table>

    {backtest_section}

    <h2>5. Piano nel tempo</h2>
    <table class="stats">
        <tr><td>Frequenza di ribilanciamento</td><td>{freq_label}</td></tr>
    </table>
    <h3>Regole di monitoraggio</h3>
    <ul>{rules_html}</ul>

    <div class="disclaimer">
        <strong>Avvertenze importanti</strong>
        <ul>{disclaimers_html}</ul>
    </div>

    <p class="meta">Portfolio Strategy Engine — Report generato automaticamente.</p>
</body>
</html>"""
    return html


def _render_comparison_html(comparison: ComparisonReport) -> str:
    """Genera l'HTML per il confronto multi-profilo."""
    # Tabella confronto
    rows = []
    for r in comparison.profiles:
        mdd = _pct(r.backtest_max_drawdown) if r.backtest_max_drawdown is not None else "n/d"
        bt_sharpe = f"{r.backtest_sharpe:.2f}" if r.backtest_sharpe is not None else "n/d"

        # Composizione sintetica
        comp_parts = []
        for cls in ["equity", "bond", "commodity", "crypto"]:
            w = r.class_allocation.get(cls, 0.0)
            if w > 0.005:
                comp_parts.append(f"{cls} {_pct(w, 0)}")
        composition = ", ".join(comp_parts) if comp_parts else "n/d"

        rows.append(
            f"<tr><td><strong>{r.profile_name.capitalize()}</strong></td>"
            f"<td class='num'>{_pct(r.effective_vol_ceiling)}</td>"
            f"<td class='num'>{_pct(r.expected_return)}</td>"
            f"<td class='num'>{r.expected_sharpe:.2f}</td>"
            f"<td class='num'>{mdd}</td>"
            f"<td>{composition}</td></tr>"
        )
    table_rows = "\n".join(rows)

    # Grafico confronto equity
    equity_chart = _chart_comparison_equity(comparison)
    equity_section = ""
    if equity_chart:
        equity_section = f"""
        <h2>Confronto equity curve</h2>
        <div class="chart">
            <img src="data:image/png;base64,{equity_chart}" />
        </div>
        """

    html = f"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="utf-8" />
<style>
    @page {{ size: A4 landscape; margin: 15mm; }}
    body {{ font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
           font-size: 10pt; color: #333; line-height: 1.4; }}
    h1 {{ color: #1565C0; border-bottom: 2px solid #1565C0; padding-bottom: 5px;
         font-size: 18pt; }}
    h2 {{ color: #1976D2; margin-top: 20px; font-size: 13pt; }}
    table {{ border-collapse: collapse; width: 100%; margin: 10px 0; font-size: 9pt; }}
    th {{ background: #E3F2FD; padding: 6px 8px; text-align: left;
         border-bottom: 2px solid #90CAF9; }}
    td {{ padding: 5px 8px; border-bottom: 1px solid #eee; }}
    .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
    .chart {{ text-align: center; margin: 15px 0; }}
    .chart img {{ max-width: 100%; }}
    .meta {{ color: #777; font-size: 8pt; }}
    .disclaimer {{ background: #F5F5F5; padding: 10px 15px; margin-top: 20px;
                  font-size: 8pt; color: #666; border-radius: 4px; }}
</style>
</head>
<body>
    <h1>Confronto profili investitore</h1>
    <p class="meta">Generato il {comparison.generation_date}</p>

    <h2>Riepilogo</h2>
    <table>
        <tr><th>Profilo</th><th>Vol target</th><th>Rend. atteso</th>
            <th>Sharpe</th><th>Max drawdown</th><th>Composizione</th></tr>
        {table_rows}
    </table>

    {equity_section}

    <div class="disclaimer">
        <p>Le stime sono basate su dati storici e modelli statistici.
           Non rappresentano garanzie di performance futura.
           Le performance passate non sono indicative dei risultati futuri.</p>
    </div>

    <p class="meta">Portfolio Strategy Engine — Report generato automaticamente.</p>
</body>
</html>"""
    return html


# ============================================================
# Generazione PDF
# ============================================================

def render_pdf(report: StrategyReport, output_path: Path | None = None) -> Path:
    """Genera il PDF per un singolo profilo.

    Se weasyprint non e' disponibile, solleva ImportError con messaggio chiaro.
    """
    try:
        import weasyprint
    except (ImportError, OSError) as e:
        raise ImportError(
            "La libreria 'weasyprint' e' necessaria per generare PDF. "
            "Installala con: pip install weasyprint. "
            "Su macOS servono anche le librerie di sistema: "
            "brew install pango gdk-pixbuf libffi. "
            f"Errore: {e}"
        )

    OUTPUT_DIR.mkdir(exist_ok=True)
    if output_path is None:
        output_path = OUTPUT_DIR / f"piano_{report.profile_name}.pdf"

    html = _render_profile_html(report)
    weasyprint.HTML(string=html).write_pdf(str(output_path))

    logger.info(f"PDF generato: {output_path}")
    return output_path


def render_comparison_pdf(
    comparison: ComparisonReport,
    output_path: Path | None = None,
) -> Path:
    """Genera il PDF di confronto multi-profilo."""
    try:
        import weasyprint
    except (ImportError, OSError) as e:
        raise ImportError(
            "La libreria 'weasyprint' e' necessaria per generare PDF. "
            "Installala con: pip install weasyprint. "
            "Su macOS servono anche le librerie di sistema: "
            "brew install pango gdk-pixbuf libffi. "
            f"Errore: {e}"
        )

    OUTPUT_DIR.mkdir(exist_ok=True)
    if output_path is None:
        output_path = OUTPUT_DIR / "confronto_profili.pdf"

    html = _render_comparison_html(comparison)
    weasyprint.HTML(string=html).write_pdf(str(output_path))

    logger.info(f"PDF confronto generato: {output_path}")
    return output_path
