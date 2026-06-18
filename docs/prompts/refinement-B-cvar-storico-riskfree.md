# Prompt per Claude Code — Refinement B: CVaR storico + risk-free realistico

> Come si usa: stessa sessione di Claude Code (terminale, Opus 4.6, dentro `Portfolio-Strategy-Engine`). Incolla il testo dentro il riquadro. Fuori dal riquadro sono note per te.
>
> Due ritocchi isolati e indipendenti dal resto. Tienili separati così, se qualcosa si rompe, sappiamo esattamente cosa.

---

## ISTRUZIONI DA INCOLLARE IN CLAUDE CODE

```
Continuiamo lo stesso progetto. Tutte le fasi + core-satellite + ri-taratura profili sono
complete e validate. Ora due ritocchi isolati. Falli entrambi ma con test separati, e NON
toccare ciò che non serve.

## RITOCCO 1 — CVaR storico al posto del CVaR parametrico (gaussiano)
Attualmente l'obiettivo CVaR usa una formula parametrica che assume rendimenti normali. Per gli
asset a code grasse (tipico delle cripto, ma anche dei crolli azionari) questo SOTTOSTIMA il
rischio di coda reale.

- Sostituisci il CVaR parametrico con il CVaR STORICO / scenario-based: calcolato sulla
  distribuzione empirica dei rendimenti (gli scenari storici reali), senza assumere normalità.
  Riskfolio-Lib lo supporta nativamente: usalo se semplifica.
- Mantieni l'interfaccia esistente (l'obiettivo si chiama sempre "min_cvar", stesso livello di
  confidenza, es. 95%): cambia solo il MODO in cui il CVaR è calcolato. Se è semplice, lascia il
  parametrico disponibile come opzione, ma il DEFAULT diventa storico.
- Assicurati che usi abbastanza scenari (i dati storici disponibili) e gestisci il caso di pochi
  dati segnalandolo.

Validazione/sanity per il ritocco 1:
- Per un portafoglio con asset a code grasse, il CVaR STORICO deve risultare MAGGIORE (più
  prudente) del CVaR gaussiano: stampane il confronto per dimostrare che ora cattura le code.
- L'ottimizzazione min_cvar resta feasible e i vincoli sono rispettati.

## RITOCCO 2 — Tasso risk-free realistico (no più valore fisso ~3% hardcoded)
Lo Sharpe usa un risk-free costante poco realistico. Rendilo configurabile e coerente.

- Il tasso risk-free deve essere un PARAMETRO configurabile in un unico punto, NON un numero
  sparso nel codice.
- Permetti due modalità: (a) un valore costante configurabile con default ragionevole (es. ~2%),
  e (b) opzionalmente una SERIE STORICA di tassi (es. tasso a breve in EUR) da usare per lo
  Sharpe nei backtest, così è coerente col periodo.
- Usa questo unico risk-free in TUTTI i punti dove si calcola lo Sharpe (statistiche di
  portafoglio della Fase 3, metriche delle strategie Fase 5, backtest Fase 6). Niente valori
  duplicati o hardcoded.

Validazione/sanity per il ritocco 2:
- Cambiando il risk-free, lo Sharpe cambia in modo coerente ovunque (un unico punto di verità).
- Nessun risk-free hardcoded residuo nel codice.

## Test (obbligatori, separati per i due ritocchi)
- CVaR: test che il CVaR storico > CVaR gaussiano su una distribuzione a code grasse nota;
  min_cvar resta feasible e rispetta i vincoli.
- Risk-free: test che lo Sharpe usi il parametro configurabile e che cambiando il rate lo Sharpe
  cambi coerentemente in tutti i moduli; nessun hardcoded.
- Verifica che TUTTI i test esistenti (tutte le fasi) continuino a passare.

## Script di esempio / dimostrazione
- Stampa un confronto CVaR gaussiano vs storico per un portafoglio con cripto (per vedere quanto
  più alto è quello storico).
- Stampa lo Sharpe di un profilo con due diversi risk-free per mostrare che il parametro funziona.

## Quando hai finito
Fermati e fammi un riepilogo: cosa hai cambiato per ciascuno dei due ritocchi, il confronto CVaR
gaussiano vs storico (numeri), come hai centralizzato il risk-free, e conferma che tutti i test
passano. Aspetta il mio ok.
```

---

## Note per te (Alessio) — non incollare in Claude Code

Controlli quando ha finito:

- **CVaR storico più prudente:** nel confronto, il CVaR storico su un portafoglio con cripto deve
  essere più ALTO (più rischio di coda) di quello gaussiano. Se sono uguali, non ha cambiato nulla.
- **Risk-free in un unico punto:** chiedigli (o controlla) che non ci siano più numeri risk-free
  sparsi/hardcoded. Cambiando il parametro, lo Sharpe deve cambiare ovunque allo stesso modo.
- **Niente regressioni:** tutti i test delle fasi precedenti devono restare verdi.

Comandi tipici:
```
pytest tests/ -v
python scripts/example_cvar_riskfree.py   # (o come lo chiama lui)
```

Portami il confronto CVaR gaussiano vs storico e la conferma "tutto verde". Con questo la lista
delle rifiniture principali è chiusa, e possiamo passare alla Fase 7 (reportistica) per dare una
faccia presentabile ai risultati.
