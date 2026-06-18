# Prompt per Claude Code — Fase 4: Profilazione cliente

> Come si usa: stessa sessione di Claude Code (terminale, Opus 4.6, dentro `Portfolio-Strategy-Engine`). Incolla il testo dentro il riquadro. Fuori dal riquadro sono note per te.

---

## ISTRUZIONI DA INCOLLARE IN CLAUDE CODE

```
Continuiamo lo stesso progetto. Fasi 1-3 complete e validate (dati, stima mu/Sigma,
motore di ottimizzazione con vincoli e frontiera). Usa i loro output e il motore di
ottimizzazione esistente. NON riscrivere i moduli precedenti.

Questa è la FASE 4: PROFILAZIONE CLIENTE. È il cuore del progetto: tradurre il PROFILO
di un investitore in INPUT concreti per il motore di ottimizzazione (obiettivo + vincoli),
e produrre il portafoglio adatto a quel profilo. NON costruire ancora le strategie nel
tempo / ribilanciamenti (sarà la Fase 5).

## Concetto
Un "profilo cliente" è un oggetto di configurazione. Da esso (più l'orizzonte temporale)
deriviamo: un tetto di rischio (volatilità massima), dei tetti per classe di attivo, e un
obiettivo di ottimizzazione. Poi chiamiamo il motore della Fase 3 e otteniamo i pesi.

L'architettura deve essere MULTI-PROFILO: i profili stanno in un file di configurazione
(es. YAML) e se ne possono definire N. Implementane 5 di esempio (vedi sotto).

## I 5 profili (proposta di partenza, mettili in configurazione così sono modificabili)

| Profilo       | Volatilità max obiettivo | Azionario max | Cripto max |
|---------------|--------------------------|---------------|------------|
| Conservativo  | ~5%                      | 20%           | 0%         |
| Moderato      | ~8%                      | 40%           | 2%         |
| Bilanciato    | ~11%                     | 60%           | 5%         |
| Dinamico      | ~15%                     | 80%           | 10%        |
| Aggressivo    | nessun tetto stretto     | 100%          | 15%        |

Tutti long-only. Aggiungi se utile un peso massimo per singolo asset (es. 25-30%) per
evitare concentrazioni eccessive. Usa i metadati di asset class dell'universo (Fase 1)
per applicare i tetti di gruppo (azionario = somma degli ETF azionari; cripto = BTC+ETH).

## Mappatura profilo -> ottimizzazione (la logica)
Per ogni profilo, l'impostazione di default deve essere:
- OBIETTIVO: massimizzare il rendimento atteso CON il vincolo di volatilità <= tetto del
  profilo (così ogni profilo "spende" tutto il suo budget di rischio per ottenere il
  massimo rendimento a quel livello). In alternativa, rendi selezionabile anche
  "massimo Sharpe entro i vincoli". Rendi l'obiettivo configurabile per profilo.
- VINCOLI: long-only + tetti per classe di attivo del profilo + eventuale max per asset.

Predisponi la mappatura in modo pulito e leggibile (dal profilo agli oggetti
PortfolioConstraints/obiettivo già usati dalla Fase 3), così è facile cambiarla.

## Orizzonte temporale (in questa fase: fa da freno)
L'orizzonte modifica il rischio AMMESSO, NON ancora un glide path nel tempo (quello sarà
Fase 5). Logica semplice e configurabile, ad esempio a fasce:
- orizzonte breve (es. < 3 anni): abbassa il profilo effettivo (più prudente) / riduci il
  tetto di volatilità;
- orizzonte medio (es. 3-7 anni): profilo invariato;
- orizzonte lungo (es. > 7 anni): profilo pieno (eventualmente leggermente più permissivo).
Documenta la regola scelta.

## IMPORTANTE sui dati
Per questa fase usa una FINESTRA STORICA LUNGA (es. dal 2015 o il massimo disponibile),
non solo 2 anni: con 2 anni di solo mercato toro i rendimenti attesi sono gonfiati e i
profili risulterebbero tutti troppo ottimisti. Gestisci con grazia gli strumenti con storia
più corta (cripto/ETF recenti): segnala, non rompere.

## Validazione automatica (parte critica)
Con log chiari:
- Per ogni profilo il portafoglio risultante è feasible e i suoi pesi rispettano i tetti
  del profilo (azionario, cripto, max per asset).
- La volatilità realizzata del portafoglio è <= (o vicina a) il tetto del profilo.
- MONOTONICITÀ: salendo di profilo (Conservativo -> Aggressivo) la volatilità attesa NON
  deve diminuire (e tipicamente cresce il rendimento atteso). Se non è monotòno, segnalalo:
  è il sintomo che la mappatura ha un problema.
- Il profilo Conservativo NON deve contenere cripto; i profili prudenti devono essere
  prevalentemente obbligazionari.
- L'orizzonte breve deve produrre un portafoglio meno rischioso di quello a orizzonte lungo
  per lo stesso profilo.

## Output standard ("contratto")
Per un dato (profilo, orizzonte) restituisci: il portafoglio (pesi + statistiche, riusando
il PortfolioResult della Fase 3) più i metadati del profilo applicato. Mantienilo stabile:
sarà l'input della Fase 5 (strategie nel tempo).

## Test (obbligatori)
- Mappatura profilo -> vincoli/obiettivo corretta.
- Tetti rispettati per ogni profilo.
- Monotonicità del rischio tra profili.
- Effetto dell'orizzonte (breve = meno rischio).
- Feasibility per tutti i profili.

## Script di esempio
Esegui TUTTI E 5 i profili sull'universo (storia lunga) e stampa una tabella comparativa:
per profilo -> pesi principali, rendimento atteso, volatilità, e (se utile) un grafico che
posiziona i 5 portafogli sul piano rischio/rendimento, sovrapposti alla frontiera efficiente.
Salva il grafico nella cartella di output.

## Quando hai finito
Fermati e fammi un riepilogo: file creati, come hai mappato profilo+orizzonte -> ottimizzazione,
i 5 profili con i loro pesi/statistiche, come lanciare test ed esempio, dove sta il grafico,
e il contratto di output. Aspetta il mio ok.
```

---

## Note per te (Alessio) — non incollare in Claude Code

Questa è la fase più "di metodo", quindi i controlli sono più di buon senso che matematici:

- **La scala ha senso?** Salendo da Conservativo ad Aggressivo, volatilità e rendimento
  attesi devono crescere in modo ordinato. Se il "Bilanciato" è più rischioso del "Dinamico",
  c'è un errore nella mappatura.
- **I profili prudenti sono davvero prudenti?** Conservativo ≈ quasi tutto bond, zero cripto.
  Se vedi il Conservativo con il 15% in BTC, qualcosa non va.
- **L'orizzonte fa effetto?** Stesso profilo, orizzonte 1 anno vs 15 anni: il primo deve
  risultare più prudente.
- **Guarda i pesi, non solo i numeri di sintesi:** apri la tabella comparativa e controlla
  che le allocazioni siano sensate e diversificate (non tutto su un asset).
- **Storia lunga:** verifica che abbia davvero usato molti anni di dati (non i soliti 2),
  altrimenti i rendimenti attesi restano gonfiati.

Comandi tipici:
```
pytest tests/ -v
python scripts/example_profiles.py   # (o come lo chiama lui)
```

Portami la tabella dei 5 profili + il grafico, e poi passiamo alla Fase 5 (le strategie nel
tempo: buy & hold vs ribilanciamenti) — dove i profili diventano strategie vere.
