# Prompt per Claude Code — Fase 7: Reportistica & piano nel tempo

> Come si usa: stessa sessione di Claude Code (terminale, Opus, dentro `Portfolio-Strategy-Engine`).
> Incolla il testo dentro il riquadro. Fuori dal riquadro sono note per te.
>
> Questa fase NON aggiunge logica finanziaria: prende ciò che il motore già calcola e lo
> trasforma in un documento leggibile (PDF) per un investitore. La regola d'oro è: il report
> deve dire la VERITÀ, comprese le incertezze. Niente promesse, niente numeri inventati.

---

## ISTRUZIONI DA INCOLLARE IN CLAUDE CODE

```
Continuiamo lo stesso progetto. Tutte le fasi 1-6 + core-satellite + refinement A-F sono complete
e validate (181 test verdi). Riusa TUTTI i moduli esistenti (estimation, optimizer, profiles,
core_satellite, strategies, walkforward). NON riscrivere logica finanziaria e NON ricalcolare a
modo tuo: il report CONSUMA gli output già esistenti (ProfileResult, CoreSatelliteResult,
StrategyResult, WalkForwardResult, ParameterEstimate) e li impagina.

Questa è la FASE 7: REPORTISTICA & PIANO NEL TEMPO. Obiettivo: dato un profilo (o tutti),
produrre un "piano d'investimento" PDF leggibile da un investitore non tecnico.

## Deliverable: report PDF, configurabile
- Genera un report PDF impaginato per UN profilo, e un comando per generarli per TUTTI i profili.
- Approccio consigliato: costruisci il contenuto come HTML+CSS e rendi il PDF da lì (es.
  weasyprint), oppure reportlab se preferisci. Scegli tu, ma:
  - aggiungi la dipendenza in requirements.txt, isolata, e gestisci con un messaggio chiaro il
    caso in cui la libreria non sia installata (non far crashare l'intero progetto all'import).
  - i grafici sono PNG generati con matplotlib (riusa quelli che già produci nelle fasi
    precedenti) e vengono incorporati nel PDF.

## Cosa deve contenere il report (per un profilo)
1. Intestazione: nome profilo, descrizione, orizzonte temporale, data di generazione.
2. Allocazione raccomandata: tabella per classe di attivo E per singolo strumento reale, con i
   metadati da config/universe.yaml (nome esteso, asset class, regione, valuta, TER). Mostra il
   peso %. Se c'è un satellite cripto (core-satellite), evidenzialo come scelta separata dal core.
3. Attese di rischio/rendimento: rendimento atteso annualizzato, volatilità attesa, Sharpe,
   CVaR 95%. DEVI scrivere chiaramente che sono STIME basate su dati storici, non garanzie.
4. Crescita simulata: equity curve del backtest (riusa Fase 5/6) e il max drawdown storico, con
   una frase che spiega "in passato in scenari simili il portafoglio è sceso fino a X%".
5. Piano nel tempo: calendario di ribilanciamento (frequenza del profilo/strategia) e regole di
   monitoraggio semplici (quando guardare, soglie di scostamento, cosa fare).
6. Grafici: almeno (a) allocazione (torta o barre), (b) crescita simulata, (c) drawdown.
7. Disclaimer finale: non è consulenza finanziaria personalizzata; stime soggette a incertezza;
   performance passata non predice quella futura.

## Confronto multi-profilo
- Una sezione (o un report a parte) che mette a confronto i 5 profili su una tabella unica:
  vol target, rendimento atteso, Sharpe, max drawdown storico, composizione sintetica per classe.
- Un grafico di confronto delle equity curve dei 5 profili.

## Output standard ("contratto")
- Una dataclass tipo StrategyReport (o ProfilePlan) che raccoglie in modo strutturato TUTTO ciò
  che va nel PDF (allocazione, strumenti, stats, metriche backtest, calendario, testi). Il
  renderer PDF prende QUESTO oggetto: così la generazione del contenuto è separata
  dall'impaginazione e testabile senza produrre un PDF.
- I file PDF vanno nella cartella output/ (es. output/piano_<profilo>.pdf e
  output/confronto_profili.pdf).

## Onestà del report (importante)
- Nessun numero "abbellito": i valori vengono SOLO dagli oggetti calcolati dal motore.
- Rendimenti/vol attesi sempre etichettati come stime annualizzate con la finestra usata.
- Se una stat manca o un profilo è infeasible, il report lo dice, non inventa.

## Validazione automatica
- Il contenuto del report (l'oggetto StrategyReport) è coerente con gli oggetti sorgente: i pesi
  sommano a 1, le classi rispettano i tetti del profilo, i numeri coincidono con quelli del
  ProfileResult/WalkForwardResult (nessun ricalcolo divergente).
- Log chiaro di quali profili sono stati generati e dove sono i file.

## Test (obbligatori)
- Costruzione di StrategyReport da un ProfileResult/CoreSatelliteResult noto: i campi (pesi,
  stats, strumenti) combaciano con la sorgente.
- I pesi nel report sommano a 1 e rispettano i vincoli del profilo.
- Generazione PDF: se la libreria è disponibile, il file viene creato e non è vuoto; se non è
  disponibile, il fallback/avviso funziona senza rompere gli altri test.
- Tutti i 181 test esistenti continuano a passare.

## Script di esempio
- scripts/example_report.py (o nome simile): genera il piano PDF per un profilo (es. Bilanciato,
  con un eventuale satellite cripto a scelta) e il report di confronto dei 5 profili. Stampa i
  percorsi dei PDF generati.

## Quando hai finito
Fermati e fammi un riepilogo: file creati, la struttura dell'oggetto StrategyReport (il
contratto), che libreria PDF hai usato e come l'hai isolata, dove stanno i PDF, e conferma che
i numeri nel report vengono dagli oggetti del motore (nessun ricalcolo) e che tutti i test
passano. Aspetta il mio ok.
```

---

## Note per te (Alessio) — non incollare in Claude Code

Qui non c'è rischio di lookahead (non si calcola nulla di nuovo), ma c'è il rischio opposto: un
report che "abbellisce". Controlli quando ha finito:

- **I numeri nel PDF combaciano col motore?** Apri il PDF e confronta vol/rendimento/Sharpe con
  quelli che stampano `example_profiles.py` / `example_walkforward.py`. Devono essere identici.
  Se il report mostra numeri più belli, c'è un ricalcolo nascosto: da rifiutare.
- **C'è il disclaimer e l'etichetta "stime, non garanzie"?** È il punto che ti protegge: le attese
  di rendimento non devono mai sembrare promesse.
- **Il satellite cripto è mostrato come scelta separata** dal core, coerente con tutto il design.
- **Niente regressioni:** `pytest tests/ -q` deve restare 181, 0 falliti; la dipendenza PDF non
  deve rompere l'import del resto del progetto se manca.

Comandi tipici:
```
pip install -r requirements.txt   # per la nuova libreria PDF
pytest tests/ -q
python scripts/example_report.py
open output/piano_bilanciato.pdf output/confronto_profili.pdf
```

Se i PDF sono leggibili, i numeri combaciano col motore e c'è il disclaimer, la Fase 7 è chiusa e
il progetto ha finalmente una "faccia presentabile". Dopo restano solo i layer pratici (Fase 8:
costi reali/fiscalità/strumenti) e l'eventuale interfaccia (Fase 9).
