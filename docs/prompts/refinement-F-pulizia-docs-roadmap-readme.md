# Prompt per Claude Code — Refinement F: pulizia documentazione (ROADMAP sez.7 + README)

> Come si usa: stessa sessione di Claude Code (terminale, Opus, dentro `Portfolio-Strategy-Engine`).
> Incolla il testo dentro il riquadro. Fuori dal riquadro sono note per te.
>
> Solo documentazione. Zero codice, zero test logici. Chiude le ultime due incongruenze della lista.

---

## ISTRUZIONI DA INCOLLARE IN CLAUDE CODE

```
Continuiamo lo stesso progetto. Tutto completo e validato fino al refinement E. Ora SOLO pulizia
di documentazione, due punti. Non toccare nessun file .py di produzione né i test.

## PUNTO 1 — ROADMAP.md: la sezione 7 è obsoleta
docs/ROADMAP.md ha una contraddizione interna:
- La sezione 5 ("Stato di avanzamento") dice che il Refinement B (CVaR storico + risk-free
  configurabile) è COMPLETATO.
- Ma la sezione 7 ("Lista delle cose da rifinire") elenca ANCORA come da fare:
  - "CVaR storico/scenario invece di quello parametrico gaussiano"
  - "Tasso risk-free più realistico per il calcolo dello Sharpe (ora ~3% costante)"
  Entrambe sono già state fatte (refinement B).

Cosa voglio:
- Aggiorna la sezione 7 togliendo (o spostando in una nuova sotto-sezione "Fatto") le due voci
  già completate dal refinement B. Non lasciare voci che il codice ha già risolto.
- Mentre ci sei, aggiungi alla sezione 5 (o 6) una riga che registra i refinement appena fatti
  in questa tornata, così lo stato è veritiero:
  - Refinement C: cripto escluse dall'ottimizzatore anche nel percorso profili (coerente con
    core-satellite; equity profili ~21/38/58/72/85%, vol 5/7/10/12/14%).
  - Refinement D: fix test annualizzazione (overflow Timestamp -> RangeIndex).
  - Refinement E: docstring Sharpe allineata al risk-free centralizzato.
- Lascia intatto il resto del ROADMAP (visione, fasi, decisioni di design).

## PUNTO 2 — README.md fermo alla sola Fase 1
README.md descrive solo "Fase 1: Modulo Dati": titolo, sezione "Struttura" e descrizioni
coprono solo i moduli dati (pipeline, data_provider, cleaning, ecc.). Ma il progetto ora copre
Fasi 1-6 + core-satellite + refinement.

Cosa voglio:
- Aggiorna il README perché rifletta lo stato reale del progetto. In particolare:
  - Titolo/intro: non più "Fase 1" ma il motore completo (dati -> stima mu/Sigma ->
    ottimizzazione -> profili -> strategie -> backtest walk-forward, con core-satellite cripto).
  - Sezione "Struttura": elenca i moduli oggi presenti in src/ con una riga di descrizione
    ciascuno (estimation, mean_estimators, cov_estimators, optimizer, frontier, constraints,
    profiles, strategies, walkforward, core_satellite, config, oltre a quelli dati già citati).
  - Aggiungi una breve sezione "Esempi" che elenca gli script in scripts/ (example_estimation,
    example_optimization, example_profiles, example_strategies, example_walkforward,
    example_core_satellite, example_ritocchi) con una riga su cosa mostra ciascuno.
  - Mantieni le istruzioni di installazione e di test (sono ancora valide).
- Tieni il README sobrio e accurato: deve descrivere ciò che il codice fa DAVVERO adesso, senza
  promettere fasi non ancora fatte (la Fase 7 reportistica è il prossimo passo, non è fatta).

## Vincoli
- Nessuna modifica a file .py (né src/ né tests/ né scripts/). Solo ROADMAP.md e README.md.
- I numeri che citi nel README/ROADMAP devono essere quelli reali e già verificati
  (vol 5/7/10/12/14%, equity ~21/38/58/72/85%, oro 12%).

## Quando hai finito
Riepilogo breve: cosa hai cambiato in ROADMAP.md (sezione 7 e stato) e in README.md, conferma
che non hai toccato codice o test. Aspetta il mio ok.
```

---

## Note per te (Alessio) — non incollare in Claude Code

- È l'ultima voce della lista: dopo questo, le 5 incongruenze trovate nella revisione sono tutte
  chiuse (1 logica + 1 test + 3 di documentazione).
- Controllo veloce: rileggi la sezione 7 del ROADMAP (non deve più elencare CVaR storico e
  risk-free come "da fare") e l'intro + "Struttura" del README (devono parlare del motore
  completo, non solo della Fase 1).
- Non serve far girare i test (non tocca codice), ma un `pytest tests/ -q` di sicurezza non fa
  male: deve restare 181, 0 falliti.

Dopo questo la base è pulita e coerente, e sei pronto per attaccare la Fase 7 (reportistica) con
documentazione che dice la verità.
