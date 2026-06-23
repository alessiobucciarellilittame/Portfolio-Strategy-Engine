"""
Dashboard Streamlit — Portfolio Strategy Engine (Fase 9).

Interfaccia web che avvolge il motore esistente (Fasi 1-8).
Lancia con: streamlit run app.py
"""

import logging
import streamlit as st
import numpy as np
import pandas as pd

from datetime import date

from src.dashboard_data import (
    load_data,
    data_version,
    estimate_params,
    build_portfolio,
    build_profile_comparison,
    build_pac_comparison,
    build_view_impact,
    can_render_pdf,
    generate_pdf_bytes,
    DashboardResult,
    ProfileComparison,
    ViewImpact,
    PROFILE_ORDER,
    DATA_END,
)
from src.profiles import load_profiles

logging.basicConfig(level=logging.WARNING)

st.set_page_config(
    page_title="Portfolio Strategy Engine",
    page_icon="📊",
    layout="wide",
)

# ============================================================
# Disclaimer (sempre visibile)
# ============================================================

st.markdown(
    '<div style="background:#FFF3E0;border-left:4px solid #FF9800;padding:10px 16px;'
    'margin-bottom:16px;font-size:0.9em;">'
    "<b>Strumento illustrativo.</b> NON e' consulenza finanziaria. "
    "Le attese di rendimento sono stime basate su dati storici, non garanzie. "
    "La fiscalita' e' indicativa e va verificata con un professionista."
    "</div>",
    unsafe_allow_html=True,
)

st.title("Portfolio Strategy Engine")

# ============================================================
# Sidebar: input
# ============================================================

with st.sidebar:
    st.header("Parametri")

    profiles_cfg = load_profiles()
    profile_name = st.selectbox(
        "Profilo investitore",
        options=list(PROFILE_ORDER),
        index=2,  # bilanciato
        format_func=lambda x: x.capitalize(),
    )

    horizon_years = st.slider("Orizzonte temporale (anni)", 1, 20, 5)

    # Metodo di stima
    mean_method = st.selectbox(
        "Metodo stima rendimenti",
        ["bayes_stein", "black_litterman"],
        index=0,
        format_func=lambda x: {
            "bayes_stein": "Bayes-Stein (storico)",
            "black_litterman": "Black-Litterman (equilibrio)",
        }[x],
        help="Bayes-Stein: shrinkage delle medie storiche. "
             "Black-Litterman: rendimenti impliciti da un benchmark di equilibrio.",
    )

    # View Black-Litterman (visibile solo con BL)
    bl_views: list[dict] = []
    if mean_method == "black_litterman":
        st.divider()
        st.subheader("View soggettive")
        n_views = st.number_input("Numero di view", 0, 5, 0, key="n_views")
        for vi in range(int(n_views)):
            st.markdown(f"**View {vi + 1}**")
            vtype = st.selectbox(
                "Tipo", ["absolute", "relative"],
                key=f"vtype_{vi}",
                format_func=lambda x: "Assoluta" if x == "absolute" else "Relativa",
            )
            if vtype == "absolute":
                instr = st.text_input("Ticker", key=f"vinstr_{vi}", placeholder="es. EQQQ.DE")
                exp_ret = st.number_input(
                    "Rendimento atteso annuo", value=0.08, step=0.01,
                    format="%.2f", key=f"vret_{vi}",
                )
                conf = st.slider(
                    "Confidenza", 0.05, 0.95, 0.50, 0.05, key=f"vconf_{vi}",
                )
                if instr.strip():
                    bl_views.append({
                        "type": "absolute",
                        "instrument": instr.strip(),
                        "expected_return": exp_ret,
                        "confidence": conf,
                    })
            else:
                long_t = st.text_input("Long ticker", key=f"vlong_{vi}", placeholder="es. CSSPX.MI")
                short_t = st.text_input("Short ticker", key=f"vshort_{vi}", placeholder="es. SXR8.DE")
                outperf = st.number_input(
                    "Outperformance attesa", value=0.02, step=0.01,
                    format="%.2f", key=f"voutp_{vi}",
                )
                conf = st.slider(
                    "Confidenza", 0.05, 0.95, 0.50, 0.05, key=f"vconf_{vi}",
                )
                if long_t.strip() and short_t.strip():
                    bl_views.append({
                        "type": "relative",
                        "long": long_t.strip(),
                        "short": short_t.strip(),
                        "outperformance": outperf,
                        "confidence": conf,
                    })

    # Cripto
    max_crypto = profiles_cfg[profile_name].group_limits.get("crypto", (0, 0))[1]
    if max_crypto > 0:
        crypto_weight = st.slider(
            "Quota satellite cripto (BTC)",
            min_value=0.0,
            max_value=float(max_crypto),
            value=0.0,
            step=0.01,
            format="%.0f%%",
            help=f"Tetto profilo: {max_crypto:.0%}. Satellite = solo BTC.",
        )
    else:
        crypto_weight = 0.0
        st.info("Profilo conservativo: cripto non disponibile.")
    satellite_mode = "btc"

    # Satellite azionario (azioni singole)
    max_stock = profiles_cfg[profile_name].group_limits.get("stock", (0, 0))[1]
    stock_weight = 0.0
    stock_tickers_input: dict[str, float] | None = None
    if max_stock > 0:
        st.divider()
        st.subheader("Satellite azionario")
        st.caption(
            "Le azioni singole sono rischio concentrato, scelto dall'utente, "
            "fuori dall'ottimizzazione. Richiedono asset_class 'stock' nell'universo."
        )
        # Trova i ticker stock disponibili
        stock_available = [
            t for t, ac in ac_map.items() if ac == "stock"
        ] if 'ac_map' in dir() else []
        if not stock_available:
            st.info(
                "Nessuna azione singola nell'universo. Per aggiungerne, "
                "inserire strumenti con asset_class 'stock' in config/universe.yaml "
                "e riscaricare i dati."
            )
        else:
            stock_selected = st.multiselect(
                "Azioni singole",
                options=stock_available,
                default=[],
                key="stock_select",
            )
            if stock_selected:
                stock_weight = st.slider(
                    "Quota satellite azionario",
                    min_value=0.0,
                    max_value=float(max_stock),
                    value=0.0,
                    step=0.01,
                    format="%.0f%%",
                    help=f"Tetto profilo: {max_stock:.0%}. Equal-weight tra le azioni selezionate.",
                )
                if stock_weight > 0:
                    stock_tickers_input = {t: 1.0 for t in stock_selected}

    # Strategia
    strategy_name = st.selectbox(
        "Strategia",
        ["buy_and_hold", "periodic", "threshold"],
        index=1,
        format_func=lambda x: {
            "buy_and_hold": "Buy & Hold",
            "periodic": "Ribilanciamento periodico",
            "threshold": "Ribilanciamento a soglia",
        }[x],
    )
    if strategy_name == "periodic":
        strategy_freq = st.selectbox(
            "Frequenza", ["monthly", "quarterly", "annual"],
            index=1,
            format_func=lambda x: {"monthly": "Mensile", "quarterly": "Trimestrale", "annual": "Annuale"}[x],
        )
    else:
        strategy_freq = "quarterly"

    capital_eur = st.number_input(
        "Capitale di riferimento (EUR)",
        min_value=1_000,
        max_value=10_000_000,
        value=100_000,
        step=10_000,
        help="Per il calcolo di costi e tasse (commissioni minime, bollo).",
    )

    # Anno di partenza backtest
    st.divider()
    backtest_start_year = st.selectbox(
        "Anno di partenza del backtest",
        options=list(range(2015, DATA_END.year)),
        index=5,  # 2020
        help="La stima dei parametri usa sempre i dati completi. "
             "Questo controllo cambia solo il periodo simulato nel backtest.",
    )
    sim_start = date(backtest_start_year, 1, 2)

    # Modalita' PAC
    st.divider()
    st.header("Modalita' investimento")
    invest_mode = st.radio(
        "Modalita'",
        ["Somma unica", "PAC"],
        index=0,
        help="Somma unica: investi tutto al giorno zero. PAC: versamenti periodici.",
    )
    pac_active = invest_mode == "PAC"

    if pac_active:
        pac_contribution = st.number_input(
            "Versamento periodico (EUR)",
            min_value=50,
            max_value=50_000,
            value=500,
            step=50,
            help="Importo fisso di ogni versamento PAC.",
        )
        pac_frequency = st.selectbox(
            "Frequenza versamenti",
            ["monthly", "quarterly", "annual"],
            index=0,
            format_func=lambda x: {
                "monthly": "Mensile",
                "quarterly": "Trimestrale",
                "annual": "Annuale",
            }[x],
        )
    else:
        pac_contribution = 500
        pac_frequency = "monthly"

    st.divider()
    refresh_data = st.checkbox("Aggiorna dati da Yahoo Finance", value=False)


# ============================================================
# Caricamento dati e stima parametri (cached)
# ============================================================

@st.cache_data(show_spinner="Caricamento dati dalla cache...")
def _load_data(refresh: bool, _data_version):
    return load_data(refresh=refresh)


@st.cache_data(show_spinner="Stima parametri mu/Sigma...")
def _estimate_params(_returns_hash, returns, mean_method_, ac_map_):
    return estimate_params(returns, mean_method=mean_method_, asset_class_map=ac_map_)


try:
    bundle = _load_data(refresh_data, data_version())
except FileNotFoundError:
    st.error(
        "Cache dati non trovata. Attiva 'Aggiorna dati da Yahoo Finance' "
        "nella sidebar per scaricare i dati, oppure esegui prima:\n\n"
        "`python scripts/example.py`"
    )
    st.stop()

returns_hash = hash(bundle.returns.values.tobytes())
prices_hash = hash(bundle.prices.values.tobytes())
ac_map = bundle.universe["asset_class"].to_dict()
params = _estimate_params(returns_hash, bundle.returns, mean_method, ac_map)


# ============================================================
# Calcolo portafoglio
# ============================================================

result: DashboardResult = build_portfolio(
    params=params,
    profile_name=profile_name,
    horizon_years=horizon_years,
    crypto_weight=crypto_weight,
    satellite_mode=satellite_mode,
    strategy_name=strategy_name,
    strategy_freq=strategy_freq,
    capital_eur=float(capital_eur),
    prices=bundle.prices,
    sim_start=sim_start,
    stock_weight=stock_weight,
    stock_tickers=stock_tickers_input,
)

report = result.report

# ============================================================
# Output: tab organizzate
# ============================================================

tab_names = ["Allocazione", "Rischio/Rendimento", "Backtest"]
if pac_active:
    tab_names.append("PAC vs Somma unica")
if bl_views:
    tab_names.append("Impatto View BL")
tab_names.extend(["Costi e Tasse", "Confronto Profili", "Report PDF"])

all_tabs = st.tabs(tab_names)
tab_idx = {name: i for i, name in enumerate(tab_names)}
tab1 = all_tabs[tab_idx["Allocazione"]]
tab2 = all_tabs[tab_idx["Rischio/Rendimento"]]
tab3 = all_tabs[tab_idx["Backtest"]]
tab_pac = all_tabs[tab_idx["PAC vs Somma unica"]] if pac_active else None
tab_bl_views = all_tabs[tab_idx["Impatto View BL"]] if bl_views else None
tab4 = all_tabs[tab_idx["Costi e Tasse"]]
tab5 = all_tabs[tab_idx["Confronto Profili"]]
tab6 = all_tabs[tab_idx["Report PDF"]]

# --- Tab 1: Allocazione ---
with tab1:
    st.subheader(f"Allocazione raccomandata — {profile_name.capitalize()}")

    if result.core_satellite and (crypto_weight > 0 or stock_weight > 0):
        sat_parts = []
        if result.core_satellite.crypto_weight_actual > 0:
            sat_parts.append(f"cripto {result.core_satellite.crypto_weight_actual:.0%}")
        if result.core_satellite.stock_weight_actual > 0:
            sat_parts.append(f"azioni {result.core_satellite.stock_weight_actual:.0%}")
        total_sat = result.core_satellite.crypto_weight_actual + result.core_satellite.stock_weight_actual
        st.info(
            f"Architettura core-satellite: core tradizionale "
            f"({1 - total_sat:.0%}) + satellite "
            f"({' + '.join(sat_parts)})."
        )

    # Tabella strumenti
    rows = []
    for a in report.allocation:
        rows.append({
            "Strumento": a.name,
            "Ticker": a.ticker,
            "Classe": a.asset_class.capitalize(),
            "Regione": a.region.capitalize(),
            "Peso": f"{a.weight:.1%}",
            "TER": f"{a.ter:.2f}%",
            "Satellite": "Si" if a.is_satellite else "",
        })
    df_alloc = pd.DataFrame(rows)
    st.dataframe(df_alloc, use_container_width=True, hide_index=True)

    # Grafico per classe
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Allocazione per classe**")
        class_df = pd.DataFrame(
            list(report.class_allocation.items()),
            columns=["Classe", "Peso"],
        )
        class_df["Peso %"] = class_df["Peso"] * 100
        st.bar_chart(class_df.set_index("Classe")["Peso %"])

    with col2:
        st.markdown("**Dettaglio strumenti**")
        instr_df = pd.DataFrame([
            {"Ticker": a.ticker, "Peso %": a.weight * 100}
            for a in report.allocation
        ])
        if not instr_df.empty:
            st.bar_chart(instr_df.set_index("Ticker")["Peso %"])


# --- Tab 2: Rischio/Rendimento ---
with tab2:
    st.subheader("Attese rischio/rendimento")
    st.caption(
        "STIME basate su dati storici e modelli statistici. "
        "Non rappresentano garanzie di performance futura."
    )

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Rendimento atteso", f"{report.expected_return:.2%}")
    col2.metric("Volatilita' attesa", f"{report.expected_volatility:.2%}")
    col3.metric("Sharpe ratio", f"{report.expected_sharpe:.2f}")
    col4.metric("CVaR 95%", f"{report.expected_cvar_95:.2%}")

    st.markdown(f"""
    | Parametro | Valore |
    |---|---|
    | Profilo | {report.profile_name.capitalize()} |
    | Orizzonte | {report.horizon_years} anni ({report.horizon_band}) |
    | Vol ceiling nominale | {report.vol_ceiling:.1%} |
    | Vol ceiling effettivo | {report.effective_vol_ceiling:.1%} |
    | Risk-free rate | {report.risk_free_rate:.2%} |
    | Finestra di stima | {report.estimation_window} |
    """)


# --- Tab 3: Backtest ---
with tab3:
    st.subheader("Backtest (out-of-sample)")

    if result.strategy_result is not None:
        bt = result.strategy_result
        m = bt.metrics

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("CAGR", f"{m['cagr']:.2%}")
        col2.metric("Volatilita'", f"{m['volatility']:.2%}")
        col3.metric("Max Drawdown", f"{m['max_drawdown']:.2%}")
        col4.metric("Sharpe", f"{m['sharpe']:.2f}")

        st.markdown(
            f"Ribilanciamenti: {m['n_rebalances']} | "
            f"Turnover totale: {m['total_turnover']:.2f} | "
            f"Periodo: {sim_start} / {DATA_END}"
        )

        # Equity curve
        st.markdown("**Equity curve**")
        chart_df = pd.DataFrame({
            "Valore portafoglio": bt.portfolio_value.values,
        }, index=bt.portfolio_value.index)
        st.line_chart(chart_df)

        # Drawdown
        cummax = bt.portfolio_value.cummax()
        dd = (bt.portfolio_value - cummax) / cummax * 100
        st.markdown("**Drawdown (%)**")
        st.area_chart(pd.DataFrame({"Drawdown": dd.values}, index=dd.index))
    else:
        st.warning("Backtest non disponibile (dati insufficienti o errore).")


# --- Tab PAC: confronto PAC vs somma unica ---
if pac_active and tab_pac is not None:
    with tab_pac:
        st.subheader("PAC vs Somma unica")
        st.caption(
            f"Versamento: {pac_contribution:,.0f} EUR "
            f"({'mensile' if pac_frequency == 'monthly' else 'trimestrale' if pac_frequency == 'quarterly' else 'annuale'}). "
            "Il confronto usa lo stesso totale investito e lo stesso periodo."
        )

        @st.cache_data(show_spinner="Simulazione PAC in corso...")
        def _build_pac(
            _params_hash, params, profile, horizon, crypto_w, sat_mode,
            strat_name, strat_freq, _prices_hash, prices,
            contribution, pac_freq, sim_start_,
        ):
            return build_pac_comparison(
                params, profile, horizon, crypto_w, sat_mode,
                strat_name, strat_freq, prices,
                contribution, pac_freq, sim_start=sim_start_,
            )

        try:
            pac_comp = _build_pac(
                returns_hash, params, profile_name, horizon_years,
                crypto_weight, satellite_mode, strategy_name, strategy_freq,
                prices_hash, bundle.prices,
                float(pac_contribution), pac_frequency, sim_start,
            )

            pac_s = pac_comp.summary["pac"]
            ls_s = pac_comp.summary["lumpsum"]

            # Metriche affiancate
            st.markdown("**Riepilogo**")
            col_pac, col_ls = st.columns(2)

            with col_pac:
                st.markdown("##### PAC")
                st.metric("Totale versato", f"{pac_s['total_invested']:,.0f} EUR")
                st.metric("Valore finale", f"{pac_s['final_value']:,.0f} EUR")
                st.metric("Guadagno", f"{pac_s['absolute_gain']:,.0f} EUR")
                st.metric("IRR (money-weighted)", f"{pac_s['irr']:.2%}")
                st.metric("Max Drawdown", f"{pac_s['max_drawdown']:.2%}")
                st.metric("Costi totali", f"{pac_s['total_costs']:,.2f} EUR")

            with col_ls:
                st.markdown("##### Somma unica")
                st.metric("Totale investito", f"{ls_s['total_invested']:,.0f} EUR")
                st.metric("Valore finale", f"{ls_s['final_value']:,.0f} EUR")
                st.metric("Guadagno", f"{ls_s['absolute_gain']:,.0f} EUR")
                st.metric("CAGR", f"{ls_s['cagr']:.2%}")
                st.metric("Max Drawdown", f"{ls_s['max_drawdown']:.2%}")
                st.metric("Costi totali", f"{ls_s['total_costs']:,.2f} EUR")

            # Curve di valore sovrapposte
            st.markdown("**Curve di valore**")
            chart_data = pd.DataFrame({
                "PAC": pac_comp.pac.portfolio_value.values,
                "Somma unica": pac_comp.lumpsum.portfolio_value.values,
            }, index=pac_comp.pac.portfolio_value.index)
            st.line_chart(chart_data)

            # Dettaglio costi PAC
            st.markdown("**Dettaglio costi PAC**")
            pac_m = pac_comp.pac.metrics
            n_contrib = pac_m["n_contributions"]
            cost_rows = [
                ("Numero versamenti", f"{n_contrib}"),
                ("Importo per versamento", f"{pac_contribution:,.0f} EUR"),
                ("Totale versato", f"{pac_m['total_invested']:,.0f} EUR"),
                ("Costi totali transazione", f"{pac_m['total_costs']:,.2f} EUR"),
                ("Costo medio per versamento", f"{pac_m['total_costs'] / n_contrib:,.2f} EUR" if n_contrib > 0 else "n/d"),
                ("Costo medio % per versamento", f"{pac_m['avg_cost_pct']:.2%}"),
            ]
            st.table(pd.DataFrame(cost_rows, columns=["Voce", "Valore"]))

            if pac_m["avg_cost_pct"] > 0.02:
                st.warning(
                    f"Il costo medio per versamento e' {pac_m['avg_cost_pct']:.1%} del versato. "
                    "Con importi piccoli la commissione minima fissa pesa molto. "
                    "Valuta di aumentare l'importo o ridurre la frequenza."
                )

            st.caption(
                "Di norma la somma unica produce un valore finale piu' alto "
                "perche' i soldi lavorano piu' a lungo, ma il PAC riduce il "
                "rischio di tempismo (investire tutto prima di un ribasso)."
            )

        except Exception as e:
            st.error(f"Errore nella simulazione PAC: {e}")


# --- Tab View BL: impatto delle view ---
if bl_views and tab_bl_views is not None:
    with tab_bl_views:
        st.subheader("Impatto delle view Black-Litterman")

        try:
            vi = build_view_impact(
                bundle.returns, bl_views,
                profile_name=profile_name,
                horizon_years=horizon_years,
            )

            if vi.validation_errors:
                for err in vi.validation_errors:
                    st.warning(err)

            # Tabella mu
            st.markdown("**Rendimenti attesi annui (%)**")
            mu_rows = []
            for t in vi.tickers:
                mu_rows.append({
                    "Ticker": t,
                    "Equilibrio": f"{vi.mu_equilibrium[t]:.2%}",
                    "Con view": f"{vi.mu_posterior[t]:.2%}",
                    "Delta": f"{vi.mu_delta[t]:+.2%}",
                })
            st.dataframe(pd.DataFrame(mu_rows), use_container_width=True, hide_index=True)

            # Grafico delta mu
            st.markdown("**Variazione rendimenti attesi (pp)**")
            delta_mu_df = pd.DataFrame({
                "Ticker": vi.tickers,
                "Delta mu (pp)": [vi.mu_delta[t] * 100 for t in vi.tickers],
            }).set_index("Ticker")
            st.bar_chart(delta_mu_df)

            # Tabella pesi
            st.markdown("**Allocazione (%)**")
            w_rows = []
            for t in vi.tickers:
                w_eq = vi.w_equilibrium.get(t, 0)
                w_post = vi.w_posterior.get(t, 0)
                if abs(w_eq) > 0.001 or abs(w_post) > 0.001:
                    w_rows.append({
                        "Ticker": t,
                        "Senza view": f"{w_eq:.1%}",
                        "Con view": f"{w_post:.1%}",
                        "Delta": f"{vi.w_delta[t]:+.1%}",
                    })
            st.dataframe(pd.DataFrame(w_rows), use_container_width=True, hide_index=True)

            # Summary
            st.markdown("**Riepilogo**")
            for s in vi.summary:
                st.markdown(f"- {s}")

        except Exception as e:
            st.error(f"Errore nel calcolo dell'impatto view: {e}")


# --- Tab 4: Costi e Tasse ---
with tab4:
    st.subheader(f"Costi e fiscalita' (capitale: {capital_eur:,.0f} EUR)")
    st.caption("Stime indicative. La fiscalita' NON costituisce consulenza fiscale.")

    if result.cost_breakdown is not None:
        cb = result.cost_breakdown

        if cb.costs_exceed_capital:
            st.error(
                "I costi superano il capitale di riferimento. "
                "Aumentare il capitale o ridurre la frequenza di ribilanciamento."
            )

        st.markdown("**Confronto CAGR**")
        cagr_data = {"CAGR lordo": cb.cagr_gross}
        if np.isfinite(cb.cagr_net_costs) and cb.cagr_net_costs > -1.0:
            cagr_data["CAGR netto costi"] = cb.cagr_net_costs
        if result.tax_breakdown is not None:
            tb = result.tax_breakdown
            if np.isfinite(tb.cagr_net_tax) and tb.cagr_net_tax > -1.0:
                cagr_data["CAGR netto tasse"] = tb.cagr_net_tax

        cols = st.columns(len(cagr_data))
        for i, (label, val) in enumerate(cagr_data.items()):
            cols[i].metric(label, f"{val:.2%}")

        # Dettaglio costi
        st.markdown("**Dettaglio costi (stima indicativa)**")
        cost_rows = [
            ("TER medio ponderato (annuo)", f"{cb.ter_drag_annual:.3%}"),
            ("TER drag totale", f"{cb.ter_drag_total:,.2f} EUR"),
            ("Spread totale", f"{cb.spread_total:,.2f} EUR"),
            ("Commissioni broker", f"{cb.commission_total:,.2f} EUR"),
            ("**Costi transazione**", f"**{cb.tx_cost_total:,.2f} EUR**"),
            ("**Costi totali**", f"**{cb.total_costs:,.2f} EUR**"),
            ("Impatto su CAGR", f"{cb.cost_impact_cagr:.3%}"),
        ]
        st.table(pd.DataFrame(cost_rows, columns=["Voce", "Valore"]))

        # Dettaglio tasse
        if result.tax_breakdown is not None:
            tb = result.tax_breakdown
            st.markdown("**Dettaglio fiscalita' (stima indicativa)**")
            tax_rows = [
                ("Imposta capital gain", f"{tb.capital_gain_tax:,.2f} EUR"),
                ("Aliquota effettiva media", f"{tb.capital_gain_rate_effective:.1%}"),
                ("Bollo annuo", f"{tb.bollo_annual:,.2f} EUR"),
                ("Bollo totale periodo", f"{tb.bollo_total:,.2f} EUR"),
                ("**Totale tasse**", f"**{tb.total_tax:,.2f} EUR**"),
                ("Impatto tasse su CAGR", f"{tb.tax_impact_cagr:.3%}"),
            ]
            st.table(pd.DataFrame(tax_rows, columns=["Voce", "Valore"]))

            for note in tb.notes:
                st.caption(f"— {note}")
    else:
        st.info("I costi vengono calcolati solo quando il backtest e' disponibile.")


# --- Tab 5: Confronto Profili ---
with tab5:
    st.subheader("Confronto 5 profili")

    @st.cache_data(show_spinner="Costruzione confronto profili...")
    def _build_comparison(_params_hash, params, horizon, _prices_hash, prices, sim_start_):
        return build_profile_comparison(params, horizon, prices, sim_start=sim_start_)

    prices_hash = hash(bundle.prices.values.tobytes())
    comp = _build_comparison(returns_hash, params, horizon_years, prices_hash, bundle.prices, sim_start)

    # Tabella
    comp_rows = []
    for i, name in enumerate(comp.names):
        mdd_str = f"{comp.max_drawdowns[i]:.2%}" if comp.max_drawdowns[i] is not None else "n/d"
        comp_rows.append({
            "Profilo": name.capitalize(),
            "Vol attesa": f"{comp.volatilities[i]:.2%}",
            "Rend. atteso": f"{comp.returns[i]:.2%}",
            "Sharpe": f"{comp.sharpes[i]:.2f}",
            "Max Drawdown": mdd_str,
        })
    st.dataframe(pd.DataFrame(comp_rows), use_container_width=True, hide_index=True)

    # Grafico composizione
    st.markdown("**Composizione per classe**")
    all_classes = sorted(set(c for ca in comp.class_allocations for c in ca))
    comp_chart = pd.DataFrame(
        [{c: ca.get(c, 0.0) * 100 for c in all_classes} for ca in comp.class_allocations],
        index=[n.capitalize() for n in comp.names],
    )
    st.bar_chart(comp_chart)


# --- Tab 6: Report PDF ---
with tab6:
    st.subheader("Genera report PDF")

    if can_render_pdf():
        if st.button("Genera PDF"):
            with st.spinner("Generazione PDF in corso..."):
                pdf_bytes = generate_pdf_bytes(report)
            if pdf_bytes:
                st.download_button(
                    label="Scarica PDF",
                    data=pdf_bytes,
                    file_name=f"piano_{profile_name}.pdf",
                    mime="application/pdf",
                )
                st.success("PDF generato con successo.")
            else:
                st.error("Errore nella generazione del PDF.")
    else:
        st.warning(
            "La generazione PDF richiede la libreria **weasyprint** e le sue "
            "dipendenze di sistema (pango, gdk-pixbuf). "
            "La dashboard resta completamente usabile senza il PDF.\n\n"
            "Per abilitare il PDF, installa:\n"
            "```\npip install weasyprint\n"
            "# macOS: brew install pango gdk-pixbuf libffi\n"
            "# Linux: apt-get install libpango-1.0-0 libgdk-pixbuf2.0-0\n```"
        )
