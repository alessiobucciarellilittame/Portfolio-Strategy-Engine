# Prompt per Claude Code — Fase 4-bis: Cripto in modalità core-satellite

> Come si usa: stessa sessione di Claude Code (terminale, Opus 4.6, dentro `Portfolio-Strategy-Engine`). Incolla il testo dentro il riquadro. Fuori dal riquadro sono note per te.
>
> Questa è una MODIFICA al modo in cui costruiamo il portafoglio, decisa dopo la Fase 6. Cambia la costruzione del portafoglio del profilo (Fase 4); le Fasi 5 e 6 lavorano sui pesi target, quindi continueranno a funzionare senza modifiche purché ricevano i pesi combinati.

---

## ISTRUZIONI DA INCOLLARE IN CLAUDE CODE

```
Continuiamo lo stesso progetto. Tutte le fasi 1-6 sono complete e validate. Ora cambiamo
COME costruiamo il portafoglio di un profilo, introducendo l'approccio CORE-SATELLITE per le
cripto. NON compromettere il motore esistente: riusa ottimizzatore, profili, strategie e
backtest.

## Motivazione
Le cripto hanno rendimenti storici estremi che distorcono l'ottimizzazione. Quindi NON devono
più entrare nell'ottimizzatore. Diventano un "satellite" deciso esplicitamente, sopra un
"core" costruito sui soli asset tradizionali.

## Nuova costruzione del portafoglio
Per un dato (profilo, orizzonte, quota_cripto):
1. CORE: esegui l'ottimizzatore SOLO sugli asset tradizionali (azioni, bond, commodity).
   ESCLUDI BTC ed ETH dall'insieme investibile del core. Applica i vincoli del profilo
   (tetti di classe per azionario/bond/commodity, tetto di volatilità, max per asset, long-only).
2. SATELLITE: una quota di cripto `crypto_weight` passata come INPUT ESPLICITO a ogni
   costruzione (default 0). DEVE essere <= al tetto cripto del profilo (Conservativo = 0%):
   se la si supera, segnala e limita al massimo consentito (non superarlo silenziosamente).
   Il satellite di default è SOLO BTC. Prevedi un'opzione di configurazione per usare in
   futuro un paniere BTC/ETH (es. equipesato), ma il default resta solo BTC.
3. COMBINA: pesi finali = pesi_core * (1 - crypto_weight) + satellite (crypto_weight su BTC).
   I pesi finali devono sommare a 1 ed essere long-only.

## Nota sul rischio (importante, documentala nel codice)
Il core è ottimizzato per rispettare il tetto di volatilità del profilo. Il satellite cripto
si aggiunge SOPRA: quindi la volatilità COMBINATA può superare il tetto nominale del profilo.
È voluto: la cripto è un rischio extra che l'utente sceglie consapevolmente, limitato dal
tetto del profilo. Però CALCOLA e RIPORTA sempre il rendimento atteso e la volatilità del
portafoglio COMBINATO, così l'effetto della cripto è trasparente. (Per ora teniamo questo
approccio semplice; un'eventuale logica "a budget di rischio riservato" la valuteremo dopo.)

## Output
Estendi il risultato del profilo per includere: i pesi del core, la quota cripto, i pesi
combinati finali, e le statistiche del portafoglio combinato (rendimento atteso, volatilità).
Mantieni la compatibilità con le Fasi 5 e 6 (che usano i pesi target combinati).

## Validazione automatica
Con log chiari:
- Il CORE non contiene MAI BTC o ETH.
- crypto_weight rispettato e non oltre il tetto del profilo (Conservativo => 0% cripto).
- Con crypto_weight = 0 il risultato deve essere IDENTICO al core puro.
- I pesi finali sommano a 1 e sono non negativi.
- Le statistiche combinate sono calcolate correttamente.

## Test (obbligatori)
- Il core esclude le cripto.
- Il tetto cripto del profilo è rispettato (e il clamp funziona se si chiede troppo).
- Conservativo con qualunque crypto_weight resta a 0% cripto.
- La matematica della combinazione (core scalato + satellite) è corretta e somma a 1.
- crypto_weight = 0 equivale al core puro.

## Script di esempio
Prendi il profilo Bilanciato e mostra DUE costruzioni affiancate: (a) crypto_weight = 0%,
(b) crypto_weight = 5% (BTC). Stampa pesi e statistiche combinate (rendimento atteso e
volatilità) delle due, così si vede chiaramente cosa aggiunge il satellite cripto (più
rendimento atteso ma anche più rischio). Se è semplice, aggiungi un mini-confronto di backtest
delle due versioni sullo stesso periodo.

## Quando hai finito
Fermati e fammi un riepilogo: file modificati/creati, come funziona la nuova costruzione
core-satellite, il confronto Bilanciato 0% vs 5% cripto, come lanciare test ed esempio, e
conferma che le Fasi 5-6 funzionano ancora. Aspetta il mio ok.
```

---

## Note per te (Alessio) — non incollare in Claude Code

Quando ha finito, controlla:

- **Il core è davvero "pulito"?** Nella costruzione con crypto_weight = 0, non deve esserci
  NIENTE cripto, e il portafoglio deve essere identico a prima (per gli asset tradizionali).
- **Il satellite si aggiunge bene?** Con il 5% su BTC: il core deve pesare il 95% e BTC il 5%,
  e i pesi devono sommare a 1.
- **Il Conservativo resta a 0% cripto** anche se chiedi una quota: il tetto del profilo deve vincere.
- **Trasparenza del rischio:** verifica che riporti la volatilità COMBINATA. Aggiungendo
  cripto, la vol sale sopra il target del profilo — è atteso, ma deve essere visibile, non
  nascosto.
- **Confronto 0% vs 5%:** dovresti vedere che il 5% di BTC alza sia il rendimento atteso sia
  la volatilità. È esattamente il senso del satellite: un rischio extra scelto da te.

Comandi tipici:
```
pytest tests/ -v
python scripts/example_core_satellite.py   # (o come lo chiama lui)
```

Portami il confronto 0% vs 5% e la conferma che i test (e le Fasi 5-6) sono ancora tutti verdi.
