# Prompt per Claude Code — Fase 9: Dashboard Streamlit (locale, pronta al deploy)

> Come si usa: stessa sessione di Claude Code (terminale, Opus, dentro `Portfolio-Strategy-Engine`).
> Incolla il testo dentro il riquadro. Fuori dal riquadro sono note per te.
>
> Questa fase NON aggiunge logica finanziaria: è la "faccia" del motore. Una dashboard che fa
> scegliere un profilo e mostra allocazione, backtest, costi/tasse e il PDF. Gira in locale ma
> deve essere già pronta a essere pubblicata (deploy) senza riscritture.

---

## ISTRUZIONI DA INCOLLARE IN CLAUDE CODE

```
Continuiamo lo stesso progetto. Fasi 1-8 complete e validate (248 test verdi). Questa è la FASE 9:
DASHBOARD. Costruisci un'interfaccia web con Streamlit che AVVOLGE il motore esistente. NON
riscrivere logica finanziaria: la dashboard chiama le funzioni già presenti
(estimation, profiles, core_satellite, strategies, walkforward, reporting, costs) e mostra i
risultati. Tieni la UI sottile: la logica sta in funzioni testabili, la UI le chiama soltanto.

## Dipendenza e struttura
- Aggiungi streamlit a requirements.txt.
- Crea app.py nella root del progetto (è la convenzione Streamlit / Streamlit Cloud).
- Metti la logica non-UI (preparazione dati per la dashboard) in un modulo testabile, es.
  src/dashboard_data.py, così la UI in app.py resta minimale e i pezzi si possono testare senza
  far partire Streamlit.

## Dati (importante: deve funzionare anche offline / in cloud senza yfinance)
- Di DEFAULT carica i prezzi dalla CACHE locale (i parquet in cache/), NON da yfinance: così la
  dashboard parte subito e funziona anche una volta pubblicata, senza dipendere dalla rete o dai
  limiti di Yahoo.
- Opzionale: una spunta "aggiorna dati da Yahoo" che rilancia la pipeline (use_cache/refresh), ma
  spenta di default.
- Usa st.cache_data / st.cache_resource per non ri-scaricare e non ri-stimare a ogni interazione
  (stima mu/Sigma è la parte cara: va cachata in base agli input).

## Input (sidebar)
- Profilo: selezione tra i 5 (conservativo … aggressivo).
- Orizzonte temporale (anni) -> influenza il tetto di vol effettivo.
- Quota satellite cripto (slider 0..tetto del profilo) e composizione satellite (solo BTC di
  default, opzione BTC/ETH).
- Tipo di strategia e frequenza (buy & hold / periodico / a soglia).
- Capitale di riferimento in EUR (per costi e tasse; default 100.000, coerente con la Fase 8).

## Output (area principale, organizzata a sezioni o tab)
1. Allocazione raccomandata: tabella per classe E per strumento reale (nome, classe, regione, TER
   da universe.yaml), con il satellite cripto evidenziato come scelta separata dal core. Grafico
   a torta/barre dell'allocazione.
2. Attese rischio/rendimento: rendimento atteso, volatilità, Sharpe, CVaR 95% — etichettati
   chiaramente come STIME basate su dati storici, non garanzie.
3. Backtest: equity curve della strategia scelta + max drawdown; metriche (CAGR, vol, Sharpe).
4. Costi e fiscalità (Fase 8): confronto lordo / netto costi / netto tasse al capitale scelto,
   con il dettaglio (TER, spread, commissioni, capital gain, bollo). Se i costi superano il
   capitale, mostra l'avviso (costs_exceed_capital), niente numeri muti.
5. Confronto profili: tabella e grafico che mettono a fianco i 5 profili (vol, rendimento atteso,
   Sharpe, max drawdown, composizione sintetica).
6. Report PDF: pulsante per generare e SCARICARE il PDF della Fase 7 per il profilo scelto
   (st.download_button). Se weasyprint non è disponibile nell'ambiente, mostra un messaggio chiaro
   invece di crashare (la dashboard resta usabile senza il PDF).

## Disclaimer (obbligatorio e visibile)
- In testa o in fondo alla pagina, sempre visibile: "Strumento illustrativo. NON è consulenza
  finanziaria. Le attese di rendimento sono stime, non garanzie. La fiscalità è indicativa."

## Pronta al deploy (senza riscritture dopo)
- requirements.txt completo e funzionante (streamlit + tutte le dipendenze già usate).
- Se per il PDF servono librerie di sistema (weasyprint richiede pango ecc.), aggiungi un
  packages.txt con i pacchetti apt necessari (è il file che Streamlit Cloud installa). Se assenti,
  la dashboard deve comunque funzionare, solo senza il bottone PDF.
- Aggiungi al README una sezione "Dashboard": come lanciarla in locale (streamlit run app.py) e
  una nota su come pubblicarla (repo su GitHub -> Streamlit Community Cloud -> deploy). Non fare il
  deploy: solo predisporre.

## Test
- Test delle funzioni di src/dashboard_data.py (NON della UI): dato un set di input (profilo,
  orizzonte, crypto, strategia, capitale), restituiscono le strutture attese (allocazione, stats,
  metriche backtest, breakdown costi/tasse) coerenti con gli oggetti del motore. Niente numeri
  inventati: devono combaciare con ProfileResult/CoreSatelliteResult/StrategyResult.
- Tutti i 248 test esistenti restano verdi.

## Quando hai finito
Fermati e fammi un riepilogo: i file creati (app.py, dashboard_data.py, packages.txt se serve),
come gira in locale (il comando), come hai cachato la stima, conferma che i numeri mostrati vengono
dal motore, e conferma che tutti i test passano. Aspetta il mio ok. NON pubblicare nulla.
```

---

## Note per te (Alessio) — non incollare in Claude Code

- Quando ha finito, la lanci in locale con:
  ```
  streamlit run app.py
  ```
  Ti si apre il browser su un indirizzo locale (tipo localhost:8501). Giochi con i menu: cambi
  profilo, orizzonte, quota cripto, strategia, e guardi se allocazione/backtest/costi cambiano in
  modo sensato.
- Cosa controllare (sei il revisore di dominio):
  - I numeri nella dashboard combaciano con quelli che già conosci dagli script
    (vol 5/7/10/12/14%, equity ~21/38/58/72/85%, oro 12%, le cripto solo come satellite).
  - Il confronto lordo/netto-costi/netto-tasse usa il capitale che scegli e i numeri sono finiti
    (niente NaN: l'abbiamo appena sistemato).
  - Il disclaimer "non è consulenza finanziaria" si vede.
- Sul PDF in cloud: weasyprint sul tuo Mac ha bisogno di `brew install pango gdk-pixbuf libffi`;
  su Streamlit Cloud serve il packages.txt. Se il bottone PDF dà problemi online, la dashboard
  deve restare usabile lo stesso — è scritto nel prompt.
- Quando sei contento di come gira in locale, il passo "pubblicazione" (GitHub -> Streamlit Cloud
  -> link condivisibile) lo facciamo dopo, con calma: è un'operazione separata e te la guido a
  parte.

Chiusa la Fase 9, hai il motore + la faccia. La Fase 10 (multi-cliente vero, MiFID, regolatorio)
è un altro mondo e si apre solo se/quando vai verso la consulenza reale.
