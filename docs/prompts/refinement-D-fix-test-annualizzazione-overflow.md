# Prompt per Claude Code — Refinement D: fix del test di annualizzazione che va in overflow

> Come si usa: stessa sessione di Claude Code (terminale, Opus, dentro `Portfolio-Strategy-Engine`).
> Incolla il testo dentro il riquadro. Fuori dal riquadro sono note per te.
>
> Micro-fix. È un bug nel TEST, non nel codice di produzione. L'annualizzazione è corretta.

---

## ISTRUZIONI DA INCOLLARE IN CLAUDE CODE

```
Continuiamo lo stesso progetto. Tutto è completo e validato fino al refinement C. Ora un
micro-fix isolato su UN test che fallisce in certi ambienti. Non toccare codice di produzione.

## IL PROBLEMA
Il test tests/test_cov_estimators.py::TestSampleCovariance::test_annualization_synthetic_known
crea un indice temporale così:

    n = 100_000
    idx = pd.bdate_range("2020-01-01", periods=n, name="date")

100.000 business day partendo dal 2020 arrivano oltre l'anno 2390, che SFORA il limite massimo
dei Timestamp di pandas (~2262, per via dei nanosecondi a 64 bit). Con pandas recente questo
solleva:
    OutOfBoundsTimedelta: Cannot cast 139999 days ... without overflow
e il test fallisce. (Nel tuo ambiente con pandas 3.x può non scattare, ma con pandas 2.x sì:
è comunque fragile e va reso robusto.)

Importante: NON è un errore di annualizzazione. La logica di SampleCovariance è giusta e gli altri
test di annualizzazione passano. L'indice datetime qui non serve a niente — la stima di covarianza
non usa le date, solo i valori e l'ann_factor passato esplicitamente.

## COSA VOGLIO
Rendi il test robusto senza cambiare ciò che verifica (std giornaliera 0.01, i.i.d. ->
var annualizzata ~ 0.01^2 * 252 = 0.0252, vol annualizzata ~ 15.87%).

- Sostituisci l'indice che va in overflow con un indice che non dipende da date reali: usa un
  semplice RangeIndex intero (pd.RangeIndex(n)) oppure, se preferisci tenere un DatetimeIndex,
  riduci la frequenza/durata così da restare entro i limiti di pandas (ma il RangeIndex è la
  scelta più pulita: il test non ha bisogno di date).
- Mantieni n grande (100_000) per la convergenza statistica e mantieni invariate le asserzioni e
  le tolleranze esistenti.
- Controlla se lo stesso pattern pd.bdate_range(..., periods=...) con n molto grande compare in
  ALTRI test e, se sì, applica lo stesso fix lì (così non ricompare).

## Test
- Il test test_annualization_synthetic_known ora passa in modo deterministico, senza overflow.
- Tutti gli altri test continuano a passare.

## Quando hai finito
Fermati e fammi un riepilogo breve: cosa hai cambiato nel test, conferma che non hai toccato
codice di produzione, e conferma "tutti i test passano, 0 falliti". Aspetta il mio ok.
```

---

## Note per te (Alessio) — non incollare in Claude Code

- È solo igiene del test: l'indice a 100k business day usciva dal calendario gestibile da pandas.
  Mettendo un indice intero il problema sparisce e il test verifica esattamente la stessa cosa.
- Controllo veloce quando ha finito:
  ```
  pytest tests/test_cov_estimators.py -v
  pytest tests/ -q
  ```
  Deve risultare "0 falliti" anche con pandas 2.x.

Chiuso questo, passiamo alla #3 (docstring sbagliata di `compute_metrics` in strategies.py: dice
rf=0 ma usa il risk-free configurato).
