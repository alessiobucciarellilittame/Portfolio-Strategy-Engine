# Prompt per Claude Code — Fase 2: Stima dei parametri (μ e Σ)

> Come si usa: nella stessa sessione di Claude Code (terminale, su Opus 4.6, dentro `Portfolio-Strategy-Engine`), incolla il testo dentro il riquadro. Fuori dal riquadro sono note per te.

---

## ISTRUZIONI DA INCOLLARE IN CLAUDE CODE

```
Continuiamo lo stesso progetto. La Fase 1 (modulo dati) è completata e validata: usa il
suo output (il DataBundle / la matrice dei rendimenti) come punto di partenza, NON
riscrivere il modulo dati.

Questa è la FASE 2: STIMA DEI PARAMETRI. Obiettivo: a partire dai rendimenti storici,
stimare in modo ROBUSTO due cose che serviranno all'ottimizzatore:
- μ (mu): il vettore dei rendimenti attesi degli strumenti
- Σ (Sigma): la matrice di covarianza dei rendimenti

NON costruire ancora l'ottimizzatore, i profili o le strategie. Solo la stima.

## Principi (importanti)
- I dati grezzi danno stime instabili: per questo servono gli stimatori "shrinkage".
- ANNUALIZZAZIONE CORRETTA E COERENTE: documenta e applica bene i fattori
  (es. media giornaliera × periodi/anno; volatilità × radice dei periodi/anno).
  Ricava il fattore di annualizzazione dalla frequenza dei dati, non hardcodato a caso,
  e spiega in un commento l'assunzione fatta.
- NIENTE LOOKAHEAD: una stima alla data T deve usare solo dati fino a T. Progetta le
  funzioni perché accettino una finestra/data di riferimento (servirà nel backtest).
- Storia sufficiente: per stime sensate usa una finestra storica adeguata (es. alcuni
  anni). Gestisci con grazia gli strumenti con storia più corta (es. cripto o ETF recenti):
  segnala il problema invece di produrre numeri silenziosamente sbagliati.

## Cosa implementare

### Stimatori dei rendimenti attesi (μ)
Crea un'interfaccia comune (es. classe astratta `MeanEstimator`) e queste implementazioni,
selezionabili per nome da configurazione:
- Media storica (semplice)
- James-Stein (shrinkage verso una media comune / grand mean)
- Bayes-Stein (shrinkage verso il portafoglio a minima varianza)
Per gli shrinkage, esponi e logga l'intensità di shrinkage usata.

### Stimatori della covarianza (Σ)
Stessa logica, interfaccia comune (es. `CovarianceEstimator`) e implementazioni:
- Covarianza campionaria (sample)
- Ledoit-Wolf (shrinkage)
- OAS (Oracle Approximating Shrinkage)
Usa pure scikit-learn dove sensato. Esponi e logga l'intensità di shrinkage.

### Selezione da configurazione
Deve essere facile scegliere "quale stimatore μ" e "quale stimatore Σ" da un parametro,
come in un menu a tendina. L'architettura deve permettere di aggiungerne altri in futuro
(es. denoising RMT, Graphical Lasso) senza riscrivere il resto.

## Validazione automatica (parte critica)
Aggiungi controlli con log chiari:
- Σ deve essere simmetrica e semidefinita positiva (PSD): controlla che gli autovalori
  siano ≥ 0 (entro tolleranza numerica). Segnala il numero di condizionamento
  (condition number) della matrice.
- Verifica che lo shrinkage migliori il condizionamento rispetto alla covarianza campionaria
  (la matrice "shrinkata" deve essere meglio condizionata).
- L'intensità di shrinkage deve stare tra 0 e 1.
- μ: nessun valore assurdo (rendimenti annualizzati palesemente fuori scala vanno segnalati).
- Sanity sugli shrinkage: la stima "shrinkata" deve cadere tra la stima grezza e il target.

## Output standard ("contratto")
Definisci con chiarezza cosa restituisce la fase: tipicamente un oggetto con il vettore μ,
la matrice Σ, i nomi degli strumenti, e metadati (stimatori usati, finestra/periodo,
fattore di annualizzazione). Questo oggetto sarà l'input della Fase 3 (ottimizzatore):
rendilo stabile e documentato.

## Test (obbligatori)
- Test unitari per ogni stimatore.
- Test che la covarianza stimata sia sempre PSD.
- Test di correttezza dell'annualizzazione su dati sintetici noti (numeri che puoi
  verificare a mano).
- Test che lo shrinkage si comporti come atteso (intensità in [0,1], stima tra grezzo e target).

## Script di esempio
Crea uno script che, sull'universo della Fase 1 con una storia adeguata:
- calcola μ e Σ con un paio di combinazioni di stimatori,
- stampa un confronto leggibile: volatilità annualizzate per strumento, numero di
  condizionamento di Σ campionaria vs Ledoit-Wolf, intensità di shrinkage, e i rendimenti
  attesi annualizzati.

## Quando hai finito
Fermati e fammi un riepilogo sintetico: file creati, come lanciare test ed esempio, quali
stimatori e quali controlli hai messo, e il contratto di output. Aspetta il mio ok prima
della fase successiva.
```

---

## Note per te (Alessio) — non incollare in Claude Code

Quando ha finito, NON fidarti del riepilogo: fai girare i test e l'esempio e **guarda i numeri**. In particolare controlla:

- **Volatilità annualizzate plausibili** (ordini di grandezza tipici): azioni ~15-20%,
  obbligazioni ~3-7%, oro ~12-16%, cripto ~50-80%. Se vedi un'azione al 2% o un bond al 40%,
  c'è un errore (probabilmente di annualizzazione).
- **Σ è PSD** e il **condition number** con Ledoit-Wolf è più basso che con la covarianza
  campionaria (lo shrinkage deve "stabilizzare").
- **Intensità di shrinkage tra 0 e 1** (se è 0 non sta facendo nulla, se è 1 ignora i dati).
- **Rendimenti attesi annualizzati** non assurdi (un'azione attesa al +200%/anno è un errore).

Comandi tipici da lanciare nel terminale:
```
pytest tests/ --network
python scripts/example.py   # o il nuovo script di esempio della Fase 2, se lo crea separato
```

Portami qui gli output e li controlliamo insieme prima della Fase 3 (motore di ottimizzazione).
