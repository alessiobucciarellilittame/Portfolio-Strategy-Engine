# Prompt per Claude Code — Refinement E: docstring dello Sharpe allineata al codice

> Come si usa: stessa sessione di Claude Code (terminale, Opus, dentro `Portfolio-Strategy-Engine`).
> Incolla il testo dentro il riquadro. Fuori dal riquadro sono note per te.
>
> Micro-fix di documentazione. Nessuna logica cambia: è una docstring che mente.

---

## ISTRUZIONI DA INCOLLARE IN CLAUDE CODE

```
Continuiamo lo stesso progetto. Tutto completo e validato fino al refinement D. Ora un micro-fix
di SOLA documentazione, niente logica.

## IL PROBLEMA
In src/strategies.py, la funzione compute_metrics() ha una docstring che dice:

    "sharpe: Sharpe ratio annualizzato (con rf=0 per semplicità sulla serie simulata)"

Ma il codice NON usa rf=0: usa il risk-free centralizzato configurabile, cioè
rf = get_risk_free_rate() (default 2%). Quindi la docstring contraddice il codice. Questo è
nato probabilmente prima del refinement B (risk-free centralizzato) e non è stato aggiornato.

## COSA VOGLIO
- Correggi la docstring di compute_metrics() così che descriva il comportamento reale: lo Sharpe
  usa il tasso risk-free centralizzato (get_risk_free_rate(), default ~2%), non zero.
- NON cambiare la logica: il calcolo dello Sharpe resta esattamente com'è.
- Mentre ci sei, fai una rapida verifica in tutto il progetto che non ci siano ALTRE docstring o
  commenti che dicono ancora "rf=0" / "risk-free zero" / "per semplicità" riferiti allo Sharpe,
  rimasti indietro rispetto al refinement B. Se ne trovi, allineali. Solo commenti/docstring,
  niente codice.

## Test
- Nessun test nuovo necessario (è documentazione). Conferma solo che TUTTI i test esistenti
  continuano a passare (181, 0 falliti).

## Quando hai finito
Riepilogo breve: quali docstring/commenti hai corretto e conferma che la logica non è stata
toccata e che i test passano. Aspetta il mio ok.
```

---

## Note per te (Alessio) — non incollare in Claude Code

- È solo allineamento testo↔codice: dopo il refinement B il risk-free è un parametro unico (~2%),
  ma questa docstring era rimasta a "rf=0". Chi legge si confonde.
- Controllo veloce: apri src/strategies.py, funzione compute_metrics, e verifica che la riga dello
  Sharpe non dica più "rf=0". `pytest tests/ -q` deve restare verde.

Chiuso questo, restano due voci di pura documentazione: la #4 (ROADMAP sezione 7 elenca ancora
CVaR storico e risk-free come "da fare" mentre il refinement B li ha già fatti) e la #5 (README
fermo alla sola Fase 1). Le possiamo accorpare in un unico prompt finale di pulizia docs, se ti va.
