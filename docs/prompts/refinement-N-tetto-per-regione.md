# Prompt per Claude Code — Refinement N: tetto per regione (anti-concentrazione)

> Come si usa: stessa sessione di Claude Code (terminale, Opus, dentro `Portfolio-Strategy-Engine`).
> Incolla il testo dentro il riquadro. Fuori dal riquadro sono note per te.
>
> Aggiunge un guardrail per evitare che l'ottimizzatore concentri tutto su un'unica area (oggi USA
> ~60% con Nasdaq + S&P entrambi al tetto del 30%). Tocca il motore (optimizer/profiles/config),
> con cura.

---

## ISTRUZIONI DA INCOLLARE IN CLAUDE CODE

```
Continuiamo lo stesso progetto. Tutto completo e validato. Ora aggiungiamo un TETTO PER REGIONE,
un guardrail di diversificazione geografica. Modifica mirata al motore, riusando i meccanismi che
già esistono.

## IL PROBLEMA
L'ottimizzatore tende a concentrarsi sui vincitori storici: con EQQQ (Nasdaq) e CSSPX (S&P 500),
entrambi region="usa", che si piantano al tetto del 30% per singolo strumento, l'azionario USA
arriva al ~60% del portafoglio. Vogliamo poter limitare l'esposizione per AREA geografica.

## COME FARLO (riusa il pattern dei vincoli di gruppo già presente)
Oggi l'optimizer applica già dei vincoli per asset_class (group_constraints + asset_class_map). Fai
la stessa identica cosa, in parallelo, per la REGIONE:
- Aggiungi un meccanismo di vincoli per regione: un region_map (ticker -> region, preso dal campo
  "region" già presente in config/universe.yaml) e dei region_constraints {regione: [min, max]}.
- Applicali nell'optimizer accanto ai vincoli per asset_class, con la stessa logica di indicizzazione
  (somma dei pesi dei ticker di quella regione tra min e max). Vale per TUTTI gli obiettivi
  pertinenti e per entrambi i percorsi (profilo diretto e core-satellite).
- Aggiungi la validazione: validate_result deve controllare anche i tetti di regione.

## CONFIGURAZIONE (profiles.yaml)
- Aggiungi a ogni profilo una sezione opzionale region_limits {regione: [min, max]}, sullo stesso
  stile di group_limits.
- Imposta un DEFAULT ragionevole che risolve la concentrazione USA, lasciando flessibilità:
  - cap sulle singole aree concentrate, es. usa: [0.0, 0.40] (e, se vuoi, europe e altre singole
    regioni a un tetto simile).
  - NON mettere un tetto a "global" (es. MSCI World): è già un indice diversificato di suo, limitarlo
    sarebbe controproducente.
  - Scegli i numeri di default in modo che restino sensati per tutti i profili e che NON rendano
    infeasible l'ottimizzazione (occhio: con tetti troppo stretti + tetto di vol, il problema può
    diventare irrisolvibile — verificalo).
- I tetti di regione sono un GUARDRAIL: la leva principale resta il tetto di volatilità.

## Propagazione
- Thread del region_map dall'universo fino all'optimizer, esattamente come già si fa con
  asset_class_map (profili, core-satellite, dashboard). Default = nessun vincolo di regione se non
  configurato, per retro-compatibilità.

## Test
- Il tetto di regione è rispettato a valle dell'ottimizzazione (es. usa <= 40%).
- Prima/dopo: mostra per Aggressivo e Bilanciato l'esposizione USA PRIMA (~60%) e DOPO (<= tetto),
  e conferma che i profili restano feasible e centrano ancora il tetto di volatilità.
- La monotonicità del rischio tra profili continua a valere.
- Tutti i test esistenti restano verdi.

## Quando hai finito
Fermati e fammi un riepilogo: come hai aggiunto i vincoli di regione (file toccati), i default
scelti in region_limits, il prima/dopo dell'esposizione USA, conferma che i profili restano feasible
e centrano la vol, e che i test passano. Aspetta il mio ok.
```

---

## Note per te (Alessio) — non incollare in Claude Code

- Cosa controllare: dopo, l'esposizione **USA non deve più superare il tetto** (es. 40%) su Aggressivo
  e Bilanciato, e i profili devono restare **feasible** (cioè l'ottimizzazione trova ancora una
  soluzione) e centrare il tetto di volatilità. Se qualche profilo diventa "infeasible", il tetto è
  troppo stretto: si allenta il numero.
- È un compromesso: meno concentrazione = portafoglio più diversificato e robusto, ma rinunci a
  parte della scommessa sul mercato che è andato meglio (USA/tech). È esattamente la decisione di
  buon senso che un tetto di regione serve a imporre. Il numero (40%? 45%?) puoi tararlo tu dopo aver
  visto l'effetto — è solo configurazione in profiles.yaml.
- Occhio: questa modifica CAMBIA le allocazioni raccomandate (è voluto). Quindi i numeri nelle schede
  Allocazione/Confronto si muoveranno. Verifica che abbiano senso.
- Come sempre: prova in locale, poi commit + push. Grazie all'auto-invalidazione cache, gli
  aggiornamenti di soli dati non chiedono più il Reboot; questo però è un cambio di CODICE, quindi il
  push ricostruisce comunque l'app online.

Dopo questo restano chiusi i tre ritocchi: PAC ✓, auto-cache ✓, backtest configurabile ✓, tetto
regione ✓. Poi attacchiamo **Black-Litterman**.
