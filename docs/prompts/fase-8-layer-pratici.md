# Prompt per Claude Code — Fase 8: Layer pratici (costi reali, fiscalità IT, FX, portafoglio esistente)

> Come si usa: stessa sessione di Claude Code (terminale, Opus, dentro `Portfolio-Strategy-Engine`).
> Incolla il testo dentro il riquadro. Fuori dal riquadro sono note per te.
>
> Fase ampia: rende i risultati REALISTICI (al netto di costi e tasse). La regola d'oro: tutto
> parametrico e dichiarato "indicativo". La fiscalità NON è consulenza fiscale: sono stime con
> aliquote configurabili. Fai le 4 sotto-parti come moduli/test SEPARATI, così se una si rompe
> sappiamo quale.

---

## ISTRUZIONI DA INCOLLARE IN CLAUDE CODE

```
Continuiamo lo stesso progetto. Fasi 1-7 complete e validate (203 test verdi). Riusa i moduli
esistenti, NON riscrivere la logica del motore. Questa è la FASE 8: LAYER PRATICI. Quattro
sotto-parti indipendenti, ognuna con i suoi test. Tutto guidato da configurazione: aliquote,
costi e spread sono PARAMETRI, non numeri sparsi nel codice. Ogni output "al netto" va sempre
mostrato accanto al "lordo", così l'effetto è trasparente.

## 8.1 — Costi reali e loro impatto
Oggi il backtest usa un costo di transazione unico in bps. Rendi i costi realistici e granulari.
- TER come drag annuo sul rendimento: ogni strumento ha già il TER in config/universe.yaml.
  Applica il TER come riduzione continua del rendimento (pro-rata giornaliero) nei backtest/
  strategie, pesato per l'allocazione. Mostra il rendimento lordo e quello al netto di TER.
- Costi di transazione per asset class: bid-ask spread tipico configurabile per classe (es.
  azionario ETF pochi bps, oro un po' di più, cripto molto di più), PIÙ commissioni broker
  configurabili (es. una commissione % con minimo fisso). Sostituisci il singolo tx_cost_bps con
  questo modello, mantenendo retro-compatibilità (un default ragionevole se non si configura
  nulla).
- Output: un riepilogo costi per un backtest (TER pagato, spread, commissioni, totale) e l'impatto
  in punti di CAGR (lordo vs netto).
Test 8.1: il netto è sempre <= lordo; con costi a zero netto == lordo; il TER drag su un anno è
coerente col TER nominale; i costi totali tornano con la somma dei singoli ribilanciamenti.

## 8.2 — Fiscalità italiana (INDICATIVA, aliquote configurabili)
Modella l'impatto fiscale italiano in modo indicativo e configurabile. NON è consulenza fiscale:
mettilo a chiare lettere e rendi ogni aliquota un parametro.
- Aliquote di default (configurabili, valori indicativi per investitore retail italiano):
  - redditi di capitale / plusvalenze su ETF e azioni: 26%
  - titoli di Stato italiani ed equiparati / white-list e sovranazionali: 12.5%
  - per gli ETF obbligazionari governativi: aliquota effettiva mista (la quota in titoli di Stato
    white-list al 12.5%, il resto al 26%): rendi configurabile una "quota agevolata" per strumento
    o per asset class, con default ragionevole per i bond governativi EUR.
  - cripto: aliquota configurabile (default 26%), MA segnala nel codice/doc che la tassazione
    cripto in Italia è in evoluzione e va verificata per l'anno corrente: non darla per fissa.
  - bollo titoli: 0.2% annuo sul controvalore del portafoglio.
- Asimmetria ETF (importante, è una regola reale italiana): le plusvalenze da ETF armonizzati sono
  "redditi di capitale" e NON sono compensabili con minusvalenze pregresse ("redditi diversi"),
  mentre le minus generate restano in un altro cassetto. Modella almeno questo a livello
  indicativo (o, come minimo, documentalo e non assumere compensazione piena tra plus e minus da
  ETF).
- Tassazione alla REALIZZAZIONE: la plusvalenza si tassa quando si vende, non sulla carta. Quindi
  un ETF ad accumulazione che non vendi differisce l'imposta (vantaggio fiscale del differimento):
  tienine conto nel calcolo dell'impatto fiscale di una strategia (un buy & hold paga meno tasse
  per via del minor realizzo rispetto a un ribilanciamento frequente).
- Output: per una strategia, stima dell'imposta dovuta (su realizzi e su bollo) e il rendimento
  netto di tasse, accanto al netto di soli costi e al lordo.
Test 8.2: aliquote a zero -> nessuna imposta; il bollo su un controvalore noto torna; una strategia
con più realizzi paga (indicativamente) più imposta sui capital gain di un buy & hold a parità di
rendimento lordo; aliquota govt 12.5% applicata correttamente alla quota agevolata.

## 8.3 — Gestione cambio (FX)
- Il nostro universo è già tutto quotato in EUR, quindi per gli strumenti attuali l'FX è neutro:
  verificalo e documentalo. Ma il modello deve gestire il caso generale: uno strumento o una
  posizione esistente in valuta estera va convertito in EUR (riusa src/fx.py) e l'eventuale
  effetto cambio va mostrato separato dal rendimento dello strumento.
- Non introdurre hedging complicato: basta conversione corretta + nota che il rischio cambio,
  se presente, non è coperto.
Test 8.3: uno strumento EUR ha effetto cambio nullo; uno strumento fittizio in USD viene convertito
e l'effetto cambio è calcolato e separato.

## 8.4 — Integrazione con un portafoglio esistente
Dato un portafoglio ATTUALE dell'investitore (mappa ticker -> controvalore, o pesi correnti +
capitale) e un portafoglio TARGET (dalla Fase 4/core-satellite), calcola il piano di transizione.
- Cosa vendere e cosa comprare per passare da attuale a target (delta per strumento).
- Turnover e costi di transazione reali della transizione (riusa 8.1).
- Imposta sui capital gain realizzati VENDENDO le posizioni in plus (riusa 8.2): mostrare il costo
  fiscale di ribilanciare un portafoglio già in guadagno (spesso conviene non vendere tutto).
- Output: lista ordini (buy/sell per strumento, importi), costo totale di transizione (costi +
  tasse), e i pesi risultanti.
Test 8.4: se attuale == target, nessun ordine e costo zero; gli ordini portano effettivamente ai
pesi target; il costo fiscale è zero se non si realizzano plus.

## Vincoli generali
- Tutto configurabile in un punto (es. un config/costs_tax.yaml o estensione dei config esistenti):
  niente aliquote/costi hardcoded sparsi.
- Ogni risultato "netto" sempre accanto al "lordo" e con etichetta "stima indicativa".
- Riusa estimation/optimizer/profiles/strategies/walkforward/reporting: la Fase 8 li AVVOLGE,
  non li riscrive. Se utile, aggiungi le voci costi/tasse al report PDF della Fase 7.
- Tutti i 203 test esistenti devono restare verdi.

## Quando hai finito
Fermati e fammi un riepilogo per ciascuna delle 4 sotto-parti: cosa hai aggiunto, dove stanno i
parametri, l'impatto su un esempio (lordo vs netto costi vs netto tasse), e conferma che tutti i
test passano. Aspetta il mio ok. NON iniziare la Fase 9.
```

---

## Note per te (Alessio) — non incollare in Claude Code

Sei tu il revisore di dominio, e qui il dominio è anche fiscale: occhio.

- **"Indicativo" davvero:** la fiscalità deve essere etichettata come stima, mai come verità
  certa. Le aliquote cambiano e i casi reali (zainetto fiscale, compensazione minus, regime
  amministrato vs dichiarativo) sono più complessi del modello. Va bene per capire l'ordine di
  grandezza dell'impatto, non per la dichiarazione dei redditi.
- **Due cose italiane da controllare che abbia preso bene:**
  - Bond governativi EUR all'aliquota agevolata (12.5%) sulla quota titoli di Stato, non 26% pieno.
  - Asimmetria ETF: le plus da ETF non compensano le minus pregresse. È la trappola classica.
- **Cripto:** la tassazione è cambiata di recente ed è in evoluzione — assicurati che sia un
  parametro e che il codice/doc dica "verificare per l'anno corrente", non un 26% scolpito.
- **Sanity sull'impatto:** dopo costi e tasse il CAGR netto deve SCENDERE rispetto al lordo, e una
  strategia che ribilancia spesso deve pagare (indicativamente) più tasse sui realizzi di un buy &
  hold. Se non è così, c'è un errore.
- Comandi tipici: `pytest tests/ -q` e lo script di esempio della fase.

Quando me lo porti, guardo prima di tutto il confronto lordo / netto-costi / netto-tasse su un
profilo, e se i due punti italiani sopra sono gestiti. Chiusa la Fase 8, resta solo la Fase 9
(interfaccia/dashboard) — che è comodità, non motore.

> Promemoria: io non sono un consulente fiscale e questo modello è a scopo illustrativo. Per scelte
> reali serve un commercialista.
