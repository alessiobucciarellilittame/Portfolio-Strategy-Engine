# Prompt per Claude Code — Black-Litterman: strato VIEW usabile (config + dashboard)

> Come si usa: stessa sessione di Claude Code, dentro `Portfolio-Strategy-Engine`.
> Incolla il testo dentro il riquadro. Fuori dal riquadro sono note per te (Alessio).
>
> Il motore delle view di BL esiste già (P, Q, Idzorek Ω, posterior — tutto testato). Quello che manca
> è renderlo USABILE: uno schema di view leggibile in config, e soprattutto la possibilità di inserire
> le view dalla DASHBOARD e vederne l'effetto live su μ e allocazione. È qui che BL diventa il
> "motore di strategia" che volevamo, non solo un'allocazione fissa.
>
> Decisioni già prese: equilibrio = market-cap; default di codice resta bayes_stein per ora (lo
> ribalteremo a BL-MC dopo aver visto le view all'opera). Convenzione: view assolute = rendimento
> TOTALE atteso; Π+rf.

---

## ISTRUZIONI DA INCOLLARE IN CLAUDE CODE

```
Continuiamo su Black-Litterman. Il motore delle view (Idzorek + posterior) è già implementato e
testato: NON riscriverlo. Ora lo rendiamo USABILE end-to-end, dalla configurazione fino alla
dashboard, con l'effetto delle view visibile e leggibile. Procedi a piccoli passi, non rompere niente,
default bayes_stein invariato, Σ invariata. Fermati alla fine per il mio ok.

## 1. SCHEMA DELLE VIEW LEGGIBILE (config/black_litterman.yaml)
Definisci/uniforma uno schema di view chiaro e documentato, con esempi commentati. Due tipi:
- ASSOLUTA: un asset/strumento ha un rendimento TOTALE atteso pari a X% annuo.
    es.  - type: absolute, instrument: EQQQ.DE, expected_return: 0.11, confidence: 0.60
- RELATIVA: lo strumento A batte lo strumento B di X% annuo.
    es.  - type: relative, long: SXR8.DE, short: EIMI.MI, outperformance: 0.02, confidence: 0.50
Regole:
- Le view si esprimono sugli STRUMENTI (l'utente sceglie l'ETF che incarna la convinzione): è
  univoco e evita l'ambiguità dell'overlap World/regionali.
- confidence è 0..1 (0 = ignora la view, 1 = quasi vincolante), tradotta in Ω con l'Idzorek già
  presente.
- La lista può essere VUOTA (default) → BL ricade sull'equilibrio, identico a oggi.
- Valida l'input: strumenti esistenti nell'universo (e nel core, non cripto), confidence in [0,1],
  campi obbligatori presenti. Errori chiari se la view è malformata.
- Documenta IN TESTA al file la convenzione: assoluta = rendimento totale (non excess); relativa =
  spread, indipendente da rf.

## 2. FUNZIONE DI "IMPATTO VIEW" (per diagnostica e dashboard)
Aggiungi in dashboard_data.py (logica non-UI) una funzione che, dati params + lista view, restituisce
un confronto strutturato:
- μ per strumento: equilibrio (Π+rf) vs posterior (μ_BL), e la differenza.
- allocazione del profilo scelto: senza view vs con view, e la differenza in punti.
- un riassunto testuale di quali asset la/le view hanno spinto su/giù.
Niente Streamlit qui dentro: solo dati, così è testabile.

## 3. DASHBOARD: PANNELLO VIEW INTERATTIVO (app.py)
Quando il metodo di stima selezionato è black_litterman, mostra nella sidebar (o in un tab dedicato)
un pannello "Le tue view di mercato":
- L'utente può aggiungere N view: tipo (assoluta/relativa), strumento/i (menu a tendina con i nomi
  leggibili dell'universo), valore atteso (%), confidenza (slider 0–100%).
- Le view inserite alimentano BL e l'output (allocazione, μ, backtest) si aggiorna di conseguenza.
- Mostra il PRIMA/DOPO con la funzione del punto 2: una tabella μ equilibrio vs μ con view, e lo
  spostamento dei pesi del profilo. Idealmente un grafico a barre del delta-peso per asset.
- Se non ci sono view, comportati esattamente come oggi (equilibrio puro).
- Rendi chiaro nell'etichetta che la view assoluta è un rendimento TOTALE annuo atteso.

## 4. DUE ESEMPI LAVORATI (script + commento)
In uno script di esempio (sullo stile di scripts/example_*.py) mostra due casi concreti end-to-end:
- View ASSOLUTA: "EQQQ 11% annuo, confidenza 60%" → quanto si muove μ di EQQQ da equilibrio a
  posterior, e quanto sale il suo peso nel profilo Dinamico.
- View RELATIVA: "Europa (SXR8) batte EM (EIMI) del 2%, confidenza 50%" → effetto sullo spread dei μ
  e sui pesi.
Stampa i numeri prima/dopo in modo leggibile.

## 5. TEST
- Parsing dello schema: assoluta e relativa costruite correttamente in (P, Q); errori su input
  malformati.
- View su strumento del core → posterior si muove nella direzione attesa; confidenza più alta →
  spostamento maggiore (monotonìa), già coperto ma verifica che valga via lo schema di config.
- Lista vuota → output identico all'equilibrio (nessuna regressione).
- La funzione "impatto view" (punto 2) restituisce numeri coerenti (somma pesi = 1, μ finiti).
- Tutti i test esistenti restano verdi; default bayes_stein, Σ e i 5 profili (feasibility + vol)
  intatti.

## QUANDO HAI FINITO
Fermati e fammi un riepilogo: lo schema di view finale (con un esempio assoluto e uno relativo); come
appare il pannello in dashboard (descrizione, non screenshot); i numeri prima/dopo dei due esempi
lavorati (punto 4); esito dei test. Conferma che senza view tutto è identico a oggi. Aspetta il mio
ok prima di committare.
```

---

## Note per te (Alessio) — non incollare in Claude Code

- **Questo è il pezzo che dà senso a tutto BL.** Finora abbiamo confrontato BL "muto" (solo
  equilibrio) con Bayes-Stein, e ovviamente l'equilibrio non batte chi insegue i vincitori in un bull
  market. Ma BL non serve a battere il backtest: serve a darti un punto di partenza onesto su cui
  applicare il TUO giudizio in modo coerente. Senza view non l'hai mai davvero usato.

- **Cosa potrai fare dopo**: aprire la dashboard, scegliere "Black-Litterman", e dire cose come
  "secondo me il Nasdaq farà l'11% l'anno prossimo, ne sono sicuro al 60%" oppure "l'Europa batterà gli
  emergenti del 2%, confidenza 50%" — e vedere subito come si sposta l'allocazione. In modo
  matematicamente pulito, non spostando i pesi a mano.

- **Perché le view sugli strumenti e non sulle "regioni"**: per via dell'overlap che abbiamo già
  incontrato (World contiene gli USA). Dire "view su EQQQ" è univoco; dire "view su USA" no. Tu scegli
  l'ETF che incarna la convinzione. È anche più onesto: stai esprimendo una view su uno strumento
  reale, comprabile.

- **La prova del nove**: quando è pronto, prova a inserire una view che rifletta la tua convinzione
  reale sul mercato e guarda se l'allocazione che ne esce ti convince. Se sì, allora a quel punto ha
  senso ribaltare il default su BL-MC: avrai un motore che parte neutrale e si muove solo dove TU hai
  una convinzione, invece di uno che insegue meccanicamente gli ultimi 5 anni.

- Come sempre: senza view tutto resta identico a oggi, quindi nessun rischio. Prova in locale, e
  committiamo solo quando ti convince.
