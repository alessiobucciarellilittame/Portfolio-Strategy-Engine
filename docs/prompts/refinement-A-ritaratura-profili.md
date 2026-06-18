# Prompt per Claude Code — Refinement A: Ri-taratura profili + tetto commodity

> Come si usa: stessa sessione di Claude Code (terminale, Opus 4.6, dentro `Portfolio-Strategy-Engine`). Incolla il testo dentro il riquadro. Fuori dal riquadro sono note per te.
>
> Contesto: dopo aver introdotto il core-satellite (cripto fuori dall'ottimizzatore), i profili risultano più conservativi del loro target di volatilità, perché i tetti per classe (soprattutto l'azionario) si attivano PRIMA che il portafoglio raggiunga il tetto di volatilità. Questa modifica ri-tara i profili.

---

## ISTRUZIONI DA INCOLLARE IN CLAUDE CODE

```
Continuiamo lo stesso progetto. Tutte le fasi 1-6 + il core-satellite sono complete e validate.
Ora RI-TARIAMO i profili. NON toccare il motore di ottimizzazione, le strategie o il backtest:
modifichiamo solo la definizione/mappatura dei profili e i loro vincoli.

## Problema da risolvere
Con le cripto ora fuori dall'ottimizzatore (core-satellite), i profili non raggiungono più il
loro target di volatilità: i tetti per classe di attivo (in particolare l'azionario) bloccano
il portafoglio PRIMA che arrivi al tetto di volatilità. Esempio: il Bilanciato ha target ~11%
ma il core esce a ~8,5%.

## Nuova filosofia dei profili
- Il TETTO DI VOLATILITÀ diventa la LEVA PRINCIPALE che definisce il livello di rischio di un
  profilo. L'obiettivo resta "massimizza il rendimento atteso con volatilità <= tetto".
- I tetti per classe di attivo diventano GUARDRAIL di sicurezza, non più la leva primaria:
  - RIMUOVI (o allenta molto) il tetto rigido sull'AZIONARIO, così è il tetto di volatilità a
    determinare quanta azione tenere. Un profilo con tetto di vol basso terrà comunque poco
    azionario in modo naturale (più azioni = più volatilità).
  - AGGIUNGI un tetto sulle COMMODITY (oro), es. 12% (configurabile): prima l'oro arrivava al
    20-25%, troppo.
  - MANTIENI: long-only, un tetto massimo per singolo asset come guardrail (es. 30%), e il
    tetto cripto per profilo (che limita il satellite).
- Mantieni il tetto cripto per profilo come prima (Conservativo 0%, fino ad Aggressivo 15%).

## Ri-taratura dei target di volatilità
Verifica che con la nuova impostazione ogni profilo raggiunga davvero ~ il suo target di
volatilità sul CORE (asset tradizionali). Se serve, aggiusta i 5 target di volatilità in modo
che:
- ogni profilo CENTRI la sua fascia di rischio (la vol ex-ante del core sia vicina al target),
- la scala resti MONOTÒNA (Conservativo < Moderato < Bilanciato < Dinamico < Aggressivo),
- il Conservativo resti prevalentemente obbligazionario e a bassa volatilità.
Documenta i valori finali scelti.

## Validazione automatica
Con log chiari:
- Per ogni profilo, la volatilità ex-ante del core è vicina al target (entro tolleranza).
- Monotonìa del rischio tra profili rispettata.
- Conservativo: ancora bond-heavy, poco azionario, 0% cripto.
- Commodity (oro) <= tetto in tutti i profili.
- Nessun singolo asset oltre il guardrail.
- Tutti i profili feasible.

## Test (aggiorna gli esistenti dove serve)
- I profili centrano i target di volatilità.
- Monotonìa.
- Tetto commodity rispettato.
- Guardrail per singolo asset rispettato.
- Verifica che core-satellite, Fase 5 e Fase 6 continuino a funzionare e che TUTTI i test
  passino.

## Script di esempio
Ri-esegui i 5 profili (storia lunga) e stampa la tabella comparativa aggiornata: per profilo,
volatilità (target vs realizzata), rendimento atteso, e i pesi principali per classe. Aggiorna
anche il grafico dei profili sulla frontiera, se serve. Salva in output.

## Quando hai finito
Fermati e fammi un riepilogo: cosa hai cambiato nei profili, i nuovi target di volatilità,
la tabella aggiornata dei 5 profili (target vs vol realizzata + pesi di classe), conferma che
l'oro è sotto il tetto e che tutti i test passano. Aspetta il mio ok.
```

---

## Note per te (Alessio) — non incollare in Claude Code

Quando ha finito, controlla:

- **Ogni profilo centra il suo target di volatilità?** Il Bilanciato deve tornare vicino
  all'11% (non più 8,5%). Confronta la colonna "target" con la "realizzata": devono essere vicine.
- **La scala è ancora ordinata?** Vol e rendimento crescono da Conservativo ad Aggressivo.
- **L'oro è sotto controllo?** Non più del ~12% in nessun profilo.
- **Il Conservativo è ancora prudente?** Tanti bond, poco azionario, zero cripto.
- **Tutto verde?** Tutti i test (incluse Fasi 5-6 e core-satellite) devono ancora passare.

Comandi tipici:
```
pytest tests/ -v
python scripts/example_profiles.py   # (o come lo chiama lui)
```

Portami la tabella aggiornata (target vs realizzata + pesi di classe). Se i profili ora
centrano i loro obiettivi, passiamo al Passo B: CVaR storico + risk-free realistico.
