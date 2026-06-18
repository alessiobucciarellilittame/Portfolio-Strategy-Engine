# Prompt per Claude Code — Fase 6: Backtest walk-forward

> Come si usa: stessa sessione di Claude Code (terminale, Opus 4.6, dentro `Portfolio-Strategy-Engine`). Incolla il testo dentro il riquadro. Fuori dal riquadro sono note per te.
>
> NOTA: questa è la fase più delicata di tutto il progetto. È quella dove si nascondono gli errori di lookahead, che gonfiano i risultati e li rendono falsi. Per questo i controlli anti-lookahead sono la parte più importante del prompt.

---

## ISTRUZIONI DA INCOLLARE IN CLAUDE CODE

```
Continuiamo lo stesso progetto. Fasi 1-5 complete e validate (dati, stima mu/Sigma,
ottimizzazione, profili, strategie a target fisso con costi). Riusa tutti questi moduli.
NON riscriverli.

Questa è la FASE 6: BACKTEST WALK-FORWARD. È la prova più seria. Finora il target di un
profilo era FISSO. Ora costruiamo la strategia DINAMICA: nel tempo si ri-stimano mu/Sigma
e si ri-ottimizza il portafoglio, simulando ciò che avremmo realmente fatto in passato.

## Come deve funzionare il walk-forward (passo per passo)
A ogni data di ribilanciamento T:
1. stima mu/Sigma usando SOLO i dati storici fino a T (finestra rolling o expanding, scegli
   e rendi configurabile; default: rolling, es. 3-5 anni),
2. esegui l'ottimizzatore con i vincoli del profilo -> nuovi pesi target,
3. mantieni quei pesi fino alla data di ribilanciamento successiva, applicando i costi di
   transazione sul turnover (riusa la logica della Fase 5),
4. registra i rendimenti REALIZZATI nel periodo successivo,
5. ripeti.
Alla fine ottieni una equity curve "out-of-sample" e la sequenza dei target nel tempo.

## ANTI-LOOKAHEAD — la regola assoluta (massima attenzione qui)
- La stima alla data T deve usare ESCLUSIVAMENTE dati con data < T (o <= T-1). MAI dati
  futuri rispetto a T.
- I rendimenti del periodo [T, T+1) sono "futuro" al momento della decisione in T: NON devono
  entrare in nessun modo nella stima o nell'ottimizzazione fatta in T.
- Scrivi una funzione di stima/decisione che riceva solo la "fetta" di dati ammessa, così è
  strutturalmente impossibile sbirciare il futuro.
- Aggiungi un TEST esplicito anti-lookahead. Idee per il test:
  - verifica che la funzione di decisione in T, se le passi dati oltre T, sollevi errore o
    non li usi (controllo strutturale);
  - test "placebo": se mescoli/permuti casualmente i rendimenti FUTURI, il risultato del
    backtest fino a T NON deve cambiare (perché non dovrebbe dipendere dal futuro).

## Confronto (fondamentale per capire se ha senso)
Confronta la strategia dinamica walk-forward con dei riferimenti:
- la stessa profilo in versione STATICA buy & hold (Fase 5),
- la stessa profilo in versione STATICA con ribilanciamento periodico (Fase 5),
- opzionale: un benchmark semplice (es. 60/40 o equipesato).
Stesse metriche per tutti (CAGR, volatilità, max drawdown, Sharpe, turnover/costi totali).

## Output standard ("contratto")
- equity curve out-of-sample della strategia dinamica + metriche,
- la sequenza dei pesi target nel tempo (per vedere come è evoluta l'allocazione),
- la tabella di confronto con le strategie statiche,
- metadati (finestra di stima, frequenza, costi, vincoli del profilo).

## Validazione automatica (parte critica)
Con log chiari:
- A OGNI ribilanciamento i pesi rispettano i vincoli del profilo (long-only, tetti di classe,
  max per asset).
- Controllo anti-lookahead passato (vedi sopra).
- "SANITY DI ONESTÀ": se lo Sharpe out-of-sample è sospettosamente alto (es. > 2.5-3 su molti
  anni) o se non c'è MAI un drawdown serio, ALZA UN AVVISO: è il sintomo tipico di lookahead
  o di un bug. Meglio un risultato modesto ma onesto che uno spettacolare e falso.
- I pesi nel tempo non devono "impazzire" (oscillazioni selvagge a ogni ribilanciamento):
  se succede, l'ottimizzazione è instabile (segnala; è il motivo per cui usiamo lo shrinkage).

## Test (obbligatori)
- Test ANTI-LOOKAHEAD (il più importante).
- Vincoli del profilo rispettati a ogni ribilanciamento lungo tutto il backtest.
- Corretto windowing della finestra di stima (rolling/expanding).
- Correttezza delle metriche (riusa/estendi i test della Fase 5).

## Script di esempio
Esegui il backtest walk-forward di un profilo (es. Bilanciato), finestra rolling, ribilancio
trimestrale, su un periodo lungo. Confronta con le versioni statiche (buy & hold e periodico).
Stampa la tabella di confronto e salva due grafici nella cartella di output:
1. le equity curve (dinamica vs statiche),
2. l'evoluzione dei pesi target nel tempo (es. grafico ad aree impilate).

## Quando hai finito
Fermati e fammi un riepilogo: file creati, come hai garantito l'anti-lookahead e quale test
lo verifica, la tabella di confronto dinamica vs statiche, dove stanno i due grafici, e il
contratto di output. Aspetta il mio ok.
```

---

## Note per te (Alessio) — non incollare in Claude Code

Questa è LA fase in cui devi essere più sospettoso. Controlli:

- **Lo Sharpe out-of-sample è credibile?** Se vedi numeri stratosferici (Sharpe > 2,5-3 su
  molti anni, o una curva che sale sempre senza mai un calo serio), NON esultare: è quasi
  sempre lookahead. Un backtest onesto ha drawdown veri (il 2020 e il 2022 devono vedersi).
- **Esiste un vero test anti-lookahead?** Apri `tests/` e controlla che ci sia, e che il test
  "placebo" (permutare il futuro non deve cambiare il passato) sia presente. Questo è il
  controllo più importante di tutto il progetto.
- **NON aspettarti che la strategia dinamica batta quella statica.** È un risultato famoso in
  finanza: ri-ottimizzare di continuo spesso rende PEGGIO di un'allocazione statica semplice,
  perché l'errore di stima si accumula. Se la dinamica perde contro buy & hold o contro il
  ribilanciamento statico, NON è un bug: è la realtà, ed è una lezione preziosa.
- **I pesi nel tempo sono stabili?** Apri il grafico ad aree: se l'allocazione salta da
  "tutto bond" a "tutto azioni" a ogni trimestre, l'ottimizzazione è instabile. Dovrebbe
  evolvere in modo graduale.

Comandi tipici:
```
pytest tests/ -v
python scripts/example_backtest.py   # (o come lo chiama lui)
```

Portami la tabella di confronto + i due grafici. Se i numeri sono onesti (drawdown veri,
Sharpe realistici) e il test anti-lookahead c'è ed è serio, allora il "motore" del tuo
progetto è completo. Da lì le fasi successive sono presentazione (report) e comodità (interfaccia).
