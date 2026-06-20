# Prompt per Claude Code — Refinement M: periodo di backtest configurabile

> Come si usa: stessa sessione di Claude Code (terminale, Opus, dentro `Portfolio-Strategy-Engine`).
> Incolla il testo dentro il riquadro. Fuori dal riquadro sono note per te.
>
> Permette di scegliere da quale anno parte la simulazione (oggi è fissa al 2020). La stima dei
> parametri resta sui dati completi: cambia solo il tratto simulato. Dashboard, non motore.

---

## ISTRUZIONI DA INCOLLARE IN CLAUDE CODE

```
Continuiamo lo stesso progetto. Tutto completo e validato. Ora rendiamo CONFIGURABILE il periodo di
backtest. Non toccare la logica del motore (estimation/optimizer/profiles): cambia solo da quando
parte la SIMULAZIONE.

## SITUAZIONE ATTUALE
In src/dashboard_data.py la data di inizio simulazione è fissa: SIM_START = date(2020, 1, 2). Sia il
backtest (build_portfolio -> simulate) sia il PAC sia il confronto profili usano
prices.loc[SIM_START:DATA_END]. Quindi la simulazione gira sempre 2020-2024.

## COSA VOGLIO
Far scegliere all'utente l'ANNO di partenza della simulazione (es. dal 2015), lasciando invariato
tutto il resto.
- Aggiungi nella sidebar della dashboard un controllo "Anno di partenza del backtest" (uno slider o
  un selectbox), con range dal 2015 (inizio dati) fino a circa DATA_END_anno − 1 (così resta almeno
  ~1 anno da simulare). DEFAULT = 2020, così senza toccare nulla il comportamento è identico a oggi.
- Propaga la data di inizio scelta a tutte le simulazioni: backtest (build_portfolio), PAC
  (build_pac_comparison / compare_pac_vs_lumpsum) e confronto profili (build_profile_comparison).
  Le funzioni che oggi usano SIM_START fisso devono accettare un parametro sim_start (con default =
  l'attuale 2020-01-02 per retro-compatibilità).
- IMPORTANTE: la stima dei parametri (mu/Sigma) e il calcolo dei pesi target NON cambiano — restano
  sui dati completi. Lo slider cambia SOLO il tratto su cui simuli la strategia già decisa. Quindi
  l'allocazione raccomandata resta uguale; cambiano la curva del backtest e le sue metriche.
- Aggiorna le etichette del periodo nella UI che oggi sono hardcoded (es. nella scheda Backtest c'è
  scritto "Periodo: 2020-01-02 / 2024-12-31"): devono riflettere l'anno scelto.

## Vincoli
- Default 2020 = nessun cambiamento rispetto a ora (verifica che i numeri di default siano identici).
- Niente modifiche a estimation/optimizer/profiles/strategies/costs/pac core: solo il passaggio del
  parametro sim_start e i controlli UI. Le funzioni in pac.py/strategies.py simulano già su un
  intervallo di prezzi che gli passi: basta passargli lo slice giusto, non riscriverle.

## Test
- Le funzioni di simulazione rispettano il sim_start passato (es. la prima data della curva
  corrisponde all'anno scelto).
- Con sim_start di default, i risultati coincidono con quelli attuali (nessuna regressione).
- Tutti i test esistenti restano verdi.

## Quando hai finito
Riepilogo breve: dove hai aggiunto il controllo, come hai propagato sim_start, conferma che
l'allocazione/le stime non cambiano (solo il tratto simulato), che il default 2020 dà gli stessi
numeri di prima, e che i test passano. Aspetta il mio ok.
```

---

## Note per te (Alessio) — non incollare in Claude Code

- Cosa controllare quando ha finito: muovendo lo slider, **l'allocazione raccomandata NON deve
  cambiare** (quella dipende dai dati completi, non dal periodo simulato). Devono cambiare solo la
  curva del backtest e le sue metriche (CAGR, drawdown). Se cambia anche l'allocazione, ha
  collegato lo slider alla parte sbagliata.
- Prova interessante: metti il profilo Aggressivo e fai partire il backtest dal **2015** invece che
  dal 2020 — così la simulazione include anche il crollo del 2018 e periodi diversi, e vedi una
  storia più lunga e meno "fortunata" del solo 2020-2024 (che è stato un quinquennio molto forte).
- Come sempre: prova in locale, poi commit + push. Grazie all'auto-invalidazione cache appena fatta,
  per i prossimi aggiornamenti di soli dati non servirà più il Reboot (per i cambi di codice come
  questo, il push ricostruisce comunque).

Dopo questo: #8 tetto per regione, poi Black-Litterman.
