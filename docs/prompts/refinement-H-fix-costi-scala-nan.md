# Prompt per Claude Code — Refinement H: fix scala costi (NaN su capitale nozionale) + guard

> Come si usa: stessa sessione di Claude Code (terminale, Opus, dentro `Portfolio-Strategy-Engine`).
> Incolla il testo dentro il riquadro. Fuori dal riquadro sono note per te.
>
> Bug reale emerso in verifica della Fase 8: con il capitale di default del motore (100) i costi
> producono un CAGR netto = NaN, propagato silenziosamente. Due cause da chiudere insieme: scala
> incoerente + assenza di guard. I test non l'hanno preso perché non esercitavano build_cost_breakdown
> su un backtest reale a capitale di default.

---

## ISTRUZIONI DA INCOLLARE IN CLAUDE CODE

```
Continuiamo lo stesso progetto. La Fase 8 (costi/fiscalità) è quasi a posto: la fiscalità è
verificata e corretta (aliquota bond mista 15.2%, bollo 0.2%, capital gain alla realizzazione).
Ma c'è un BUG di scala nei costi e una lacuna di test. Sistemali. Tocca src/costs.py, la
config se serve, gli script/report se serve, e i test.

## IL BUG — CAGR netto = NaN per incoerenza di unità
Tutto il motore usa un capitale NOZIONALE di default = 100 (le equity curve partono da 100; vedi
simulate()/run_walkforward()). Ma il modello costi della Fase 8 usa fee in valore ASSOLUTO in EUR:
in particolare broker_minimum_eur = 1.50 EUR per ordine. Con un backtest reale (es. ribilanciamento
mensile, ~121 ribilanciamenti, più strumenti per ordine) la somma dei minimi assoluti arriva a
~1400 EUR, ma il portafoglio "vale" ~100-190 (nozionale). Risultato: il valore netto va NEGATIVO e
il calcolo del CAGR fa (valore_negativo) ** (frazione) = NaN, che viene restituito e finisce dritto
nel report senza un solo warning.

Prova a riprodurlo: build_cost_breakdown su un backtest 'periodic monthly' del profilo bilanciato
con initial_capital=100 (il default) -> cagr_net_costs è NaN. Con initial_capital=100_000 invece è
sano (netto < lordo). Quindi è un problema di scala + mancanza di guard.

## COSA VOGLIO (due fix insieme)

1) Coerenza di scala tra costi e capitale.
   - I costi assoluti (minimo commissione in EUR) hanno senso solo su un capitale REALE in EUR, non
     sul nozionale 100. Rendi esplicito e coerente l'uso:
   - Aggiungi a build_cost_breakdown / build_tax_breakdown / build_transition_plan un parametro
     esplicito di capitale di riferimento in EUR (es. capital_eur), con un default REALISTICO
     (es. 100_000 EUR) usato per tradurre i pesi/percentuali in importi su cui applicare le fee
     assolute. In alternativa, se preferisci, scala internamente l'equity curve nozionale a questo
     capitale prima di applicare i costi. L'importante è che le fee assolute non vengano mai
     applicate contro un portafoglio da 100 nozionali.
   - Documenta chiaramente: "i costi assoluti (minimo commissione) richiedono un capitale di
     riferimento in EUR; il default è X". Lo script di esempio della Fase 8 e la sezione costi del
     report PDF devono usare questo capitale realistico, non il nozionale 100.

2) Guard anti-NaN (gli errori devono essere RUMOROSI, non silenziosi).
   - Nel calcolo del CAGR netto: se il valore netto del portafoglio diventa <= 0 (costi che
     "mangiano" tutto il capitale), NON restituire NaN da una potenza di base negativa. Invece:
     logga un WARNING chiaro ("costi superiori al capitale: capitale insufficiente / scala errata")
     e restituisci un valore sensato e segnalato (es. -1.0 = -100%, oppure float('nan') ma con un
     campo/flag esplicito che indica il problema), così non passa inosservato.
   - Stessa protezione ovunque si calcoli un CAGR su un valore potenzialmente non positivo
     (cost breakdown e tax breakdown).

## LACUNA DI TEST
- Aggiungi un test che esegue build_cost_breakdown su un backtest REALE (multi-ribilanciamento) con
  un capitale di riferimento realistico e verifica che cagr_net_costs sia FINITO (non NaN) e <=
  cagr_gross. Questo avrebbe preso il bug.
- Aggiungi un test del guard: se i costi superano il capitale, la funzione NON restituisce un NaN
  silenzioso ma logga/segnala il problema in modo verificabile.
- Verifica che la stessa protezione valga per build_tax_breakdown.

## Verifica finale
- Riproduci il caso prima/dopo: a capitale realistico il netto è finito e < lordo; a capitale
  insufficiente parte il warning e non c'è NaN muto.
- Tutti i 239 test esistenti restano verdi.
- Rigenera lo script di esempio Fase 8 e, se la sezione costi/tasse è nel report PDF, controlla che
  i numeri nel PDF siano finiti e sensati.

## Quando hai finito
Riepilogo breve: come hai reso coerente la scala (parametro capitale + default), come hai messo il
guard anti-NaN, i test aggiunti, e conferma che il caso a capitale 100 non produce più NaN muto e
che tutti i test passano. Aspetta il mio ok.
```

---

## Note per te (Alessio) — non incollare in Claude Code

- È lo stesso tipo di problema della Fase 7: una cosa che "funziona" nei test costruiti ma si rompe
  sul percorso reale. Qui i 36 test passavano perché nessuno chiamava build_cost_breakdown su un
  backtest vero a capitale di default. L'ho beccato facendo girare il modello end-to-end.
- La radice è concettuale: il motore lavora con un capitale nozionale 100 (comodo per le %), ma le
  commissioni con minimo fisso in EUR hanno senso solo su un capitale reale. O dichiari un capitale
  di riferimento, o le fee assolute vanno tradotte: il prompt chiede di farlo esplicito.
- Controllo quando ha finito: chiedigli di stampare il confronto lordo / netto-costi / netto-tasse
  su un profilo a capitale realistico (es. 100.000 EUR) — i numeri devono essere tutti finiti e in
  ordine decrescente. E prova tu il caso "capitale piccolo": deve uscire un WARNING, non un NaN.
- Minore (non bloccante): in src/strategies.py:170 c'è un FutureWarning di pandas su pct_change
  (fill_method deprecato). Quando capita, può chiedergli di passare fill_method=None per togliere
  il rumore — ma è cosmetico, non urgente.

Comandi tipici:
```
pytest tests/ -q
python scripts/example_costs.py   # (o come si chiama)
```

Chiuso questo, la Fase 8 è davvero solida: fiscalità verificata, costi a scala corretta, niente
NaN nascosti. Da lì resta solo la Fase 9 (interfaccia/dashboard).
