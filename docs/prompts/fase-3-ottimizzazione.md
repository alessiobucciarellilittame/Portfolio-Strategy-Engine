# Prompt per Claude Code — Fase 3: Motore di ottimizzazione

> Come si usa: stessa sessione di Claude Code (terminale, Opus 4.6, dentro `Portfolio-Strategy-Engine`). Incolla il testo dentro il riquadro. Fuori dal riquadro sono note per te.

---

## ISTRUZIONI DA INCOLLARE IN CLAUDE CODE

```
Continuiamo lo stesso progetto. Fase 1 (dati) e Fase 2 (stima di mu e Sigma) sono complete
e validate. Usa il loro output (il ParameterEstimate con mu, Sigma, tickers) come input.
NON riscrivere i moduli precedenti.

Questa è la FASE 3: MOTORE DI OTTIMIZZAZIONE. Obiettivo: dato un insieme di asset, le stime
mu/Sigma e un insieme di VINCOLI, trovare i pesi del portafoglio ottimale. NON costruire
ancora profili cliente o strategie nel tempo: solo il motore di ottimizzazione.

## Librerie
Puoi usare Riskfolio-Lib e/o CVXPY (con un risolutore come Clarabel/ECOS). Però INCAPSULA
la libreria dietro una nostra interfaccia pulita, così resta sostituibile e il resto del
codice non dipende direttamente da Riskfolio.

## Cosa implementare

### Funzioni obiettivo (risk measures) — set iniziale, estensibile
Crea un'interfaccia comune e queste implementazioni, selezionabili per nome:
- Mean-Variance (Markowitz): con varianti di obiettivo
  - minima varianza
  - massimo Sharpe (rendimento/rischio)
  - massimo rendimento dato un tetto di rischio (o minimo rischio dato un rendimento target)
- CVaR (Conditional Value at Risk)
- Minima varianza pura (min-variance)
Progetta un "registry" come nelle fasi precedenti, così aggiungerne altri (EVaR, MAD, ecc.)
in futuro è banale.

### Vincoli (fondamentali, qui si governa il rischio)
- Somma dei pesi = 1 (interamente investito); prevedi l'opzione di lasciare liquidità.
- Long-only on/off (no posizioni corte se attivo).
- Peso minimo e massimo per singolo asset.
- Vincoli per GRUPPO / classe di attivo (es. "cripto totale <= 15%", "azionario <= 70%").
  Usa i metadati di asset class già presenti nell'universo (Fase 1).
- Return floor opzionale: rendimento atteso minimo del portafoglio (mu^T w >= soglia).
I vincoli devono essere passabili da configurazione, in modo pulito.

### Modalità
- Portafoglio singolo: dato un obiettivo + vincoli, restituisci i pesi.
- Frontiera efficiente: traccia la curva rischio/rendimento (una serie di portafogli
  ottimali al variare del livello di rischio/rendimento target).

## Validazione automatica (parte critica)
Con log chiari:
- I pesi sommano a 1 (entro tolleranza).
- Tutti i vincoli sono rispettati (min/max per asset, long-only, tetti di gruppo, return floor).
- Lo stato del risolutore è "ottimale": se il problema è INFEASIBLE (vincoli incompatibili),
  NON restituire numeri a caso — segnala chiaramente l'infeasibilità e spiega il probabile motivo.
- Sanity check:
  - il portafoglio a minima varianza deve avere volatilità <= di un portafoglio equipesato;
  - SENZA vincoli e con i mu storici (dove BTC ha rendimento atteso altissimo), l'ottimizzatore
    a massimo rendimento tenderà a concentrarsi su BTC: mostralo, perché dimostra PERCHÉ
    servono i vincoli;
  - CON un tetto sulle cripto (es. 15%) il peso su BTC deve rispettarlo.

## Output standard ("contratto")
Definisci cosa restituisce: i pesi per asset, le statistiche del portafoglio (rendimento
atteso, volatilità, e la misura di rischio usata, es. CVaR), e metadati (obiettivo, vincoli
applicati, stato del solver). Questo sarà l'input delle fasi successive (strategie/backtest):
rendilo stabile e documentato.

## Test (obbligatori)
- Casi piccoli con soluzione nota/analitica (es. min-variance a 2 asset) per verificare la
  correttezza numerica.
- Test che i vincoli vengano rispettati (min/max, long-only, tetti di gruppo, return floor).
- Test del comportamento in caso di vincoli infeasibili (deve segnalare, non inventare).
- Test che la frontiera efficiente sia coerente (rischio crescente -> rendimento crescente,
  curva concava).

## Script di esempio
Sull'universo della Fase 1, con le stime della Fase 2:
- ottimizza con un paio di obiettivi (es. minima varianza e massimo Sharpe), una volta SENZA
  vincoli e una volta con vincoli sensati (long-only, max 15% cripto, max 10% per singolo asset);
- stampa i pesi e le statistiche in modo leggibile;
- calcola la frontiera efficiente e salva un grafico (immagine) nella cartella di output.

## Quando hai finito
Fermati e fammi un riepilogo: file creati, obiettivi e vincoli implementati, come lanciare
test ed esempio, dove ha salvato il grafico della frontiera, e il contratto di output.
Aspetta il mio ok.
```

---

## Note per te (Alessio) — non incollare in Claude Code

Quando ha finito, fai girare e **controlla**:

- **I pesi sommano a 1** e (se long-only) nessun peso è negativo.
- **I vincoli sono rispettati**: con "max 15% cripto" la somma BTC+ETH deve essere ≤ 15%;
  con "max 10% per asset" nessun peso supera il 10%.
- **La prova del nove sul perché servono i vincoli**: senza vincoli, l'ottimizzatore a
  massimo rendimento dovrebbe buttarsi quasi tutto su BTC (per via del rendimento atteso
  gonfiato). È il comportamento atteso e la dimostrazione concreta del problema di cui
  parlavamo. Con i vincoli, invece, il portafoglio deve diventare ragionevole e diversificato.
- **La frontiera efficiente**: apri l'immagine salvata. Deve essere una curva che sale
  (più rischio → più rendimento) e "piega" verso l'alto-sinistra (concava). Se è una linea
  strana o frastagliata, c'è qualcosa che non va.
- **Infeasibilità**: prova a chiedere qualcosa di impossibile (es. max 1% per asset su 10
  asset = somma max 10% ≠ 100%) e verifica che si lamenti invece di restituire numeri finti.

Comandi tipici:
```
pytest tests/ -v --network
python scripts/example_optimization.py   # (o come lo chiama lui)
```

Portami gli output + dimmi cosa vedi nel grafico della frontiera, e poi decidiamo la Fase 4
(profilazione cliente: dal profilo ai vincoli e all'obiettivo — il cuore del tuo progetto).
