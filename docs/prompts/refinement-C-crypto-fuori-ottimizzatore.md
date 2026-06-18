# Prompt per Claude Code — Refinement C: cripto fuori dall'ottimizzatore anche nel percorso profili

> Come si usa: stessa sessione di Claude Code (terminale, Opus, dentro `Portfolio-Strategy-Engine`).
> Incolla il testo dentro il riquadro. Fuori dal riquadro sono note per te.
>
> Bug di coerenza, non di crash: il percorso profili (Fase 4) e il percorso core-satellite danno
> allocazioni diverse perché solo uno dei due rispetta la decisione di design "cripto fuori
> dall'ottimizzatore". Questo ritocco li riallinea. Niente altro va toccato.

---

## ISTRUZIONI DA INCOLLARE IN CLAUDE CODE

```
Continuiamo lo stesso progetto. Tutte le fasi + core-satellite + i due refinement (A e B) sono
completi e validati. Ora UN solo ritocco di coerenza, isolato. Non toccare ciò che non serve.

## IL PROBLEMA
Per design (vedi ROADMAP, registro decisioni, e il commento in config/profiles.yaml) le cripto
NON devono entrare nell'ottimizzatore: il "core" si ottimizza sui soli asset tradizionali
(azioni, bond, oro) e le cripto si aggiungono solo come satellite opt-in tramite
build_core_satellite().

Ma il percorso profili di Fase 4 NON rispetta questa regola. In profiles.py,
build_portfolio_for_profile() / build_all_profiles() passano il group_limit crypto
(es. crypto: [0, 0.15]) come VINCOLO all'ottimizzatore. Risultato: il solver mette davvero le
cripto dentro il core (2/5/10/15%), contraddicendo il design. Infatti le allocazioni divergono:

- Percorso profili diretto (build_all_profiles, usato da example_profiles.py):
  equity ~ 29.7 / 44.8 / 62.6 / 66.7 / 67.3%
- Percorso core-satellite (quello voluto):
  equity ~ 19.6 / 34.5 / 57.2 / 71.7 / 85.3%

La calibrazione scritta nel commento di profiles.yaml (~21/38/58/72/85% equity) corrisponde al
core-satellite, NON a ciò che build_all_profiles produce oggi. Quindi codice e documentazione
sono in contraddizione.

## COSA VOGLIO
Fai sì che il percorso profili (Fase 4) escluda SEMPRE le cripto dall'ottimizzazione, esattamente
come fa già build_core_satellite. Il "core" del profilo è per definizione solo asset tradizionali.

Requisiti precisi:
- In build_portfolio_for_profile() (e quindi build_all_profiles()) le cripto vanno ESCLUSE dai
  parametri prima di ottimizzare. Riusa la logica di filtro già esistente in
  core_satellite._filter_params (NON duplicarla: se serve, spostala/centralizzala in un punto
  condiviso — es. estimation.py o un modulo util — e fai importare entrambi da lì).
- Il group_limit "crypto" in profiles.yaml NON deve più essere passato come vincolo
  all'ottimizzatore. Resta nel YAML SOLO come tetto del satellite, consumato da
  build_core_satellite(). Togli quindi il vincolo crypto dai group_constraints quando costruisci
  i PortfolioConstraints del core (di nuovo, come fa già core_satellite quando filtra
  group_limits).
- Identifica le cripto tramite asset_class == "crypto" usando l'asset_class_map, non per ticker
  hardcoded.
- NON cambiare nulla del comportamento di build_core_satellite: quello è già corretto. L'obiettivo
  è che build_all_profiles produca esattamente gli stessi core_weights/core_stats che produce
  build_core_satellite con crypto_weight=0.
- I tetti di volatilità restano centrati: con le cripto fuori, i core devono comunque dare
  vol = 5/7/10/12/14% e oro cappato al 12%, e l'equity deve tornare ai valori ~21/38/58/72/85%.

## Documentazione da riallineare
- Aggiorna il commento di calibrazione in config/profiles.yaml se necessario (deve descrivere ciò
  che il codice fa davvero ora: cripto fuori dall'ottimizzatore, tetto crypto = solo satellite).
- Aggiorna ROADMAP.md dove serve per dire che il percorso profili è ora coerente con la decisione
  core-satellite.

## Test (obbligatori)
- Test che nel percorso profili (build_all_profiles / build_portfolio_for_profile) NESSUN asset
  con asset_class "crypto" abbia peso > 0, per tutti i profili.
- Test di equivalenza: per ogni profilo, i pesi del core da build_all_profiles coincidono (entro
  tolleranza numerica) con i core_weights di build_core_satellite(crypto_weight=0).
- Test che i 5 profili continuino a centrare i target di vol (5/7/10/12/14%) e che l'oro resti
  <= 12%.
- Aggiorna eventuali test esistenti che oggi danno per scontato che le cripto stiano DENTRO
  l'ottimizzatore nel percorso profili (vanno corretti per riflettere il nuovo comportamento
  voluto).
- Verifica che TUTTI gli altri test esistenti continuino a passare.

## Script di esempio
- Aggiorna scripts/example_profiles.py se mostra/stampa pesi cripto nel core: ora il core è
  traditional-only. Le cripto compaiono solo nel percorso/esempio core-satellite.

## Quando hai finito
Fermati e fammi un riepilogo: cosa hai cambiato in profiles.py (e dove hai centralizzato il
filtro), conferma con i numeri che build_all_profiles ora dà equity ~21/38/58/72/85% e vol
5/7/10/12/14% senza cripto, conferma l'equivalenza con i core di build_core_satellite, e conferma
che tutti i test passano. Aspetta il mio ok.
```

---

## Note per te (Alessio) — non incollare in Claude Code

Cosa controllare quando ha finito:

- **Niente cripto nel core dei profili:** stampa i pesi di `build_all_profiles` — la riga crypto
  deve essere 0 per tutti e cinque. Se vedi ancora 2/5/10/15%, non ha fatto il filtro giusto.
- **Equity tornata alta:** l'aggressivo deve tornare a ~85% equity (non ~67%). Se l'equity è
  ancora schiacciata, le cripto stanno ancora rubando budget di vol dentro l'ottimizzatore.
- **Equivalenza core ↔ core-satellite:** i pesi del core nei due percorsi devono coincidere.
  È il vero test che il bug è chiuso.
- **Niente regressioni:** tutti i test delle fasi precedenti restano verdi; i target di vol
  (5/7/10/12/14%) e il tetto oro 12% restano rispettati.

Comandi tipici:
```
pytest tests/ -v
python scripts/example_profiles.py
```

Nota di merito: la decisione che stiamo cementando è "il profilo = core tradizionale; le cripto
sono SEMPRE e SOLO un satellite scelto a parte". È la scelta più onesta col cliente e coerente con
tutto il resto del progetto. Se un domani volessi invece l'opzione "cripto dentro l'ottimizzatore"
come modalità alternativa esplicita, è un'altra feature separata — non mescoliamola con questo fix.

Chiuso questo, passiamo alla #2 (il test di annualizzazione che va in overflow).
