# Prompt per Claude Code — Fase 5: Strategie nel tempo

> Come si usa: stessa sessione di Claude Code (terminale, Opus 4.6, dentro `Portfolio-Strategy-Engine`). Incolla il testo dentro il riquadro. Fuori dal riquadro sono note per te.

---

## ISTRUZIONI DA INCOLLARE IN CLAUDE CODE

```
Continuiamo lo stesso progetto. Fasi 1-4 complete e validate (dati, stima, ottimizzazione,
profili). Usa il portafoglio-obiettivo prodotto dalla Fase 4 (i pesi target di un profilo)
e i dati di prezzo della Fase 1. NON riscrivere i moduli precedenti.

Questa è la FASE 5: STRATEGIE NEL TEMPO. Finora un profilo produce una "foto" (pesi a una
data). Ora trasformiamo quella foto in una STRATEGIA che vive nel tempo, simulata sui prezzi
storici. In questa fase il TARGET resta FISSO (i pesi del profilo): la ri-stima e
ri-ottimizzazione dinamica nel tempo sarà la Fase 6 (backtest walk-forward). NON farla ora.

## Cosa implementare

### Tre tipi di strategia (interfaccia comune + registry, come nelle altre fasi)
1. Buy & Hold (passiva): all'inizio investi nei pesi target, poi non fai più nulla. I pesi
   "derivano" col mercato (cambiano da soli al variare dei prezzi). Zero ribilanciamenti.
2. Ribilanciamento periodico: a frequenza fissa (DEFAULT: trimestrale; configurabile:
   mensile/trimestrale/annuale) riporti i pesi al target.
3. Ribilanciamento a soglia: ribilanci solo quando un peso si allontana dal target oltre una
   soglia (DEFAULT: ±5 punti percentuali; configurabile). Altrimenti lasci correre.

### Costi di transazione (obbligatori)
Applica un costo realistico sul "turnover" (la quota di portafoglio effettivamente scambiata)
a ogni ribilanciamento. Default configurabile, es. ~10 punti base (0,10%) sul nozionale
scambiato. Buy & Hold non ha costi dopo l'acquisto iniziale.

### Simulazione
Simula il valore del portafoglio nel tempo sui prezzi storici:
- parti da un capitale iniziale (es. 100),
- fai evolvere i pesi giorno per giorno coi prezzi,
- applica i ribilanciamenti secondo le regole della strategia, sottraendo i costi,
- REGOLA ANTI-LOOKAHEAD: la simulazione usa solo i prezzi realizzati man mano; il target è
  fissato all'inizio (dai dati fino alla data di partenza), non con dati futuri.

## Output standard ("contratto")
Per ogni strategia restituisci una serie storica del valore del portafoglio + le metriche:
- rendimento totale e annualizzato (CAGR)
- volatilità annualizzata
- max drawdown
- Sharpe (annualizzato)
- numero di ribilanciamenti e costi totali / turnover totale
Più i metadati (tipo strategia, frequenza/soglia, costi usati). Mantienilo stabile: sarà
la base per la reportistica (Fase 7).

## Validazione automatica (parte critica)
Con log chiari:
- I pesi sommano sempre a ~1 e (long-only) restano non negativi per tutta la simulazione.
- Buy & Hold: 0 ribilanciamenti e ~0 costi dopo l'acquisto iniziale.
- Ribilanciamento periodico: numero di ribilanciamenti coerente con la frequenza
  (es. trimestrale su N anni ≈ 4*N).
- Ribilanciamento a soglia: i ribilanciamenti avvengono SOLO quando la deriva supera la soglia.
- I costi riducono il rendimento rispetto a una versione senza costi (sanity).
- Max drawdown e annualizzazione corretti (verificali su una serie sintetica nota).

## Test (obbligatori)
- Logica di ogni strategia (quando ribilancia e quando no).
- Calcolo e applicazione dei costi sul turnover.
- Correttezza di CAGR, volatilità annualizzata e max drawdown su serie sintetiche note.
- Niente lookahead.

## Script di esempio
Prendi UN profilo (es. Bilanciato) e fai girare TUTTE E TRE le strategie sullo stesso periodo
storico lungo. Stampa una tabella comparativa (rendimento annualizzato, volatilità, max
drawdown, n. ribilanciamenti, costi totali) e salva un grafico con le tre "equity curve"
(crescita del capitale nel tempo) sovrapposte. Salva il grafico nella cartella di output.

## Quando hai finito
Fermati e fammi un riepilogo: file creati, le tre strategie, come gestisci i costi, come
lanciare test ed esempio, dove sta il grafico, e il contratto di output. Aspetta il mio ok.
```

---

## Note per te (Alessio) — non incollare in Claude Code

Quando ha finito, controlla:

- **Le equity curve hanno senso?** Apri il grafico: devono crescere nel tempo con i cali noti
  ben visibili (il crollo Covid di marzo 2020, il calo del 2022). Se una curva è piatta o
  esplode in modo assurdo, c'è un errore.
- **Buy & Hold non fa trade** dopo l'inizio (0 ribilanciamenti, ~0 costi).
- **Le strategie con ribilanciamento** fanno più operazioni e hanno un piccolo "drag" da costi,
  ma di solito tengono il rischio più vicino al target.
- **ATTENZIONE a un equivoco comune**: il ribilanciamento NON sempre rende di più del buy &
  hold. In mercati molto direzionali (come questi anni con le azioni in forte salita) il buy &
  hold può rendere di più, perché lascia correre i vincitori. Il valore del ribilanciamento è
  il CONTROLLO DEL RISCHIO (volatilità e drawdown più contenuti e stabili), non il rendimento
  massimo. Quindi se vedi buy & hold con rendimento più alto ma anche drawdown più alto, NON è
  un bug: è esattamente il trade-off atteso.
- **Max drawdown plausibile**: per un profilo bilanciato aspettati cali a doppia cifra nei
  periodi brutti; se vedi un max drawdown dello 0,5% o del 95%, qualcosa non torna.

Comandi tipici:
```
pytest tests/ -v
python scripts/example_strategies.py   # (o come lo chiama lui)
```

Portami la tabella comparativa + il grafico delle equity curve, e poi passiamo alla Fase 6:
il backtest walk-forward, dove il portafoglio si ri-stima e ri-ottimizza nel tempo (la prova
più seria, e quella dove si nascondono gli errori di lookahead).
