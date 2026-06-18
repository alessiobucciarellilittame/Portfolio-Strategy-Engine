# Prompt per Claude Code — Refinement J: rimozione ETH (recupero finestra di stima al 2015)

> Come si usa: stessa sessione di Claude Code (terminale, Opus, dentro `Portfolio-Strategy-Engine`).
> Incolla il testo dentro il riquadro. Fuori dal riquadro sono note per te.
>
> Scoperta in verifica: ETH ha storia solo dal nov-2017, e siccome il motore scarta le date con
> dati mancanti, ETH tagliava il 2015-2017 dalla stima PER TUTTI gli strumenti. Togliendo ETH la
> finestra torna a 10 anni (2015-2024). BTC (storia dal 2015) resta come unico satellite cripto.

---

## ISTRUZIONI DA INCOLLARE IN CLAUDE CODE

```
Continuiamo lo stesso progetto. Tutto completo e validato (espansione universo inclusa). Ora un
intervento mirato: RIMUOVERE ETH (Ethereum) dal progetto, per recuperare la finestra di stima.

## PERCHE'
ETH-EUR ha dati solo dal novembre 2017. La stima dei parametri scarta le date in cui anche un solo
strumento ha dati mancanti (dropna), quindi la presenza di ETH taglia gli anni 2015-2017 dalla
finestra di stima PER TUTTI gli strumenti (azioni, bond, oro, BTC inclusi). Verificato: con ETH la
finestra effettiva e' ~2017-11 -> 2024 (~7 anni); senza ETH torna a 2015-01 -> 2024 (~10 anni,
~500 osservazioni in piu'). BTC ha storia dal 2015, quindi resta.

## COSA FARE
1. Rimuovi ETH-EUR da config/universe.yaml. BTC-EUR resta (unico strumento cripto / satellite).
2. Rigenera la cache prezzi (pipeline con refresh) per 2015-01-02 / 2024-12-31, cosi' la cache NON
   contiene piu' la colonna ETH. Mantieni nome e formato file invariati
   (cache/prices_2015-01-02_2024-12-31.parquet). Verifica che la nuova cache abbia 15 strumenti e
   che la finestra di stima risultante parta dal 2015 (non piu' dal 2017).
3. Satellite cripto: il default e' gia' solo BTC. Rimuovi/disabilita l'opzione "BTC + ETH (50/50)"
   dove compare:
   - nella dashboard (app.py): togli la scelta "btc_eth" dalla composizione satellite (resta solo
     BTC; se rimane una sola opzione, puoi anche togliere del tutto il selettore della composizione).
   - in src/core_satellite.py: la costante BTC_ETH_SATELLITE puoi LASCIARLA definita ma non usata
     (con un commento "ETH rimosso, riaggiungibile in futuro"), oppure rimuoverla pulendo i
     riferimenti. Scegli la via piu' pulita, ma non lasciare codice che punta a un ticker ETH
     inesistente.
4. Aggiorna i test che usano ETH o il satellite BTC+ETH (es. in test_core_satellite e nei test
   della dashboard): vanno adattati alla nuova realta' (solo BTC). Nessun test deve riferirsi a ETH.
5. Lascia tracce per il futuro: un commento in config/universe.yaml che spiega che ETH e' stato
   rimosso per non accorciare la finestra di stima, e che si puo' riaggiungere (riaggiungendo la
   riga e riscaricando la cache) quando avra' storia sufficiente o se si accetta la finestra piu'
   corta.

## VERIFICA
- La nuova cache ha 15 strumenti, niente ETH, e la stima parte dal 2015 (dimmi la finestra esatta).
- Mostra per un paio di profili (Bilanciato, Aggressivo) le stats con la finestra a 10 anni
  (rendimento atteso, vol, Sharpe) cosi' vediamo l'effetto del recupero dello storico.
- Conferma che la dashboard gira (niente piu' opzione BTC+ETH) e che il satellite BTC funziona.
- Tutti i test passano.

## Quando hai finito
Fermati e fammi un riepilogo: cosa hai rimosso, la finestra di stima finale (deve partire dal 2015),
le stats prima/dopo per un paio di profili, come hai gestito l'opzione satellite e i test, e conferma
che tutto e' verde. Aspetta il mio ok.
```

---

## Note per te (Alessio) — non incollare in Claude Code

- Il controllo chiave quando ha finito: la **finestra di stima deve partire dal 2015** (non piu'
  dal 2017). Se te lo conferma, abbiamo recuperato i 3 anni di storia.
- Aspettati che i **rendimenti attesi cambino un po'** rispetto a prima: e' normale e voluto, ora la
  stima usa 10 anni invece di 7 (incluso il forte 2015-2017 azionario). Non e' un bug, e' piu'
  storia.
- La dashboard: nella sidebar non dovresti piu' vedere la scelta "BTC + ETH (50/50)" — solo BTC come
  satellite. Provala in locale.

### Quando e' fatto e verificato — mandalo online
Cambiano di nuovo i dati (la cache) oltre al codice:
1. GitHub Desktop: vedrai modificati universe.yaml, la cache .parquet, app.py e qualche test.
2. Commit (es. "Rimozione ETH: finestra stima al 2015") -> Push origin.
3. L'app online si rigenera con la finestra a 10 anni.

Prima provala in locale (streamlit run app.py). Quando ETH avra' qualche anno di storia in piu', o
se vorrai accettare la finestra piu' corta in cambio di averlo, lo riaggiungiamo in due minuti.
