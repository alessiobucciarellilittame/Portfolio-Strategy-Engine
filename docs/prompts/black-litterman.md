# Prompt per Claude Code — Black-Litterman (stima rendimenti attesi)

> Come si usa: stessa sessione di Claude Code (terminale, Opus, dentro `Portfolio-Strategy-Engine`).
> Incolla il testo dentro il riquadro. Fuori dal riquadro sono note per te (Alessio), non incollarle.
>
> Questo è il grande tema dopo i ritocchi: sostituire/affiancare le medie storiche rumorose (il
> punto debole attuale di μ) con un prior di equilibrio + le tue view. Tocca il cuore della stima
> (Fase 2), quindi va fatto con cura, a piccoli passi verificabili e SENZA rompere nulla di esistente.

---

## ISTRUZIONI DA INCOLLARE IN CLAUDE CODE

```
Continuiamo lo stesso progetto. Tutto è completo e validato (181 test verdi). Ora aggiungiamo
BLACK-LITTERMAN come nuovo metodo di stima dei rendimenti attesi (μ). È una modifica importante al
motore di stima: falla in modo modulare, configurabile, retro-compatibile e BEN TESTATA. Procedi a
piccoli passi e fermati alla fine per il mio ok. Non rompere niente di esistente: bayes_stein resta
il default finché non lo cambio io.

## OBIETTIVO E INQUADRAMENTO
Black-Litterman parte da un portafoglio di EQUILIBRIO, ne ricava i rendimenti impliciti (reverse
optimization), e li combina con delle VIEW soggettive (opzionali) per produrre un μ posteriore più
stabile e sensato delle medie storiche. Vantaggi attesi: anche a ZERO view, μ_BL = rendimenti di
equilibrio, cioè un prior stabile che elimina il rumore delle medie storiche. Con le view, posso
inclinare il portafoglio secondo il mio giudizio in modo matematicamente coerente.

Regole di design del progetto che restano valide:
- Le CRIPTO non entrano nell'ottimizzatore: BL opera SOLO sul core tradizionale (azioni, bond, oro),
  esattamente come fanno già profiles/core_satellite via filter_params. L'equilibrio e le view sono
  definiti sui soli asset del core.
- Valuta base EUR, risk-free centralizzato (src/config.py).
- Niente lookahead: nei backtest la stima usa solo dati fino ad as_of; le view sono statiche da
  configurazione (nessun dato futuro).
- Tutto guidato da configurazione.

## SCELTE DI DESIGN GIÀ DECISE (implementa queste, non reinventarle)
1. EQUILIBRIO = benchmark strategico configurabile (NON market-cap reali, che su un universo di soli
   ETF non sono puliti). Definisci i pesi di equilibrio in configurazione a livello di asset class,
   distribuiti dentro la classe. Reverse optimization: Π = δ · Σ · w_eq.
2. VIEW = manuali, configurabili e OPZIONALI. Senza view → μ_BL = Π (retro-compatibile e stabile).
   Supporta view ASSOLUTE ("equity USA: +6% annuo atteso") e RELATIVE ("equity Europa batte equity
   USA del 2% annuo").
3. CONFIDENZA = metodo di Idzorek (confidenza intuitiva 0–100% per ciascuna view → matrice Ω), nella
   forma CHIUSA / non iterativa (la più accurata ed efficiente). Niente Ω "a occhio".

## ARCHITETTURA (importante: BL NON è un semplice MeanEstimator)
Gli stimatori attuali hanno firma estimate(returns, ann_factor). BL invece ha bisogno anche di Σ,
dei pesi di equilibrio, di δ, τ e delle view. Quindi:
- Crea un modulo nuovo `src/black_litterman.py` con la logica pura e testabile (funzioni chiare:
  costruzione w_eq normalizzati, calcolo δ, Π = δΣw_eq, parsing view → (P, Q), Idzorek → Ω,
  posterior μ_BL). Niente I/O dentro le funzioni di calcolo.
- Wira BL dentro `estimate_parameters` (src/estimation.py) come ramo speciale quando
  mean_method="black_litterman": prima si stima Σ con il cov_method scelto (Ledoit-Wolf di default),
  poi si calcola Π da quella Σ, poi si applicano le view → μ_BL. Restituisci sempre il solito
  ParameterEstimate (μ = μ_BL, cov = Σ stimata invariata).
- DECISIONE: BL modifica SOLO μ. La covarianza usata dall'ottimizzatore resta la Σ stimata
  (Ledoit-Wolf), per coerenza col resto del progetto. Calcola pure la covarianza posteriore di BL
  M = [(τΣ)⁻¹ + PᵀΩ⁻¹P]⁻¹ e mettila nei metadata a scopo diagnostico, ma NON cambiare la Σ passata
  all'ottimizzatore (a meno che non te lo chieda io in futuro).

## MATEMATICA (implementala in modo numericamente stabile: usa solve, non inversioni esplicite)
- Pesi di equilibrio w_eq: presi dalla config a livello di asset class e distribuiti dentro ogni
  classe (equal-weight dentro la classe come default, configurabile), poi NORMALIZZATI sui soli
  asset effettivamente presenti nel core (dopo l'esclusione cripto). Devono sommare a 1.
- Risk aversion δ: calibrato dall'equilibrio come δ = (μ_target − rf) / σ²_eq, dove σ²_eq = w_eqᵀ Σ
  w_eq, rf = risk-free centralizzato, e μ_target = rendimento atteso di equilibrio target (parametro
  di config, default ragionevole tipo 5–6% annuo per il benchmark). Se il risultato è assurdo,
  fallback a δ = 2.5 e LOGGALO. Esponi sia δ sia τ in configurazione.
- τ (tau): scalare piccolo, default 0.05, configurabile.
- Rendimenti impliciti: Π = δ · Σ · w_eq.
- View: costruisci P (k×n) e Q (k×1) dalla config. Assoluta → riga di P con 1 sull'asset (o pesi su
  un gruppo/classe), Q = rendimento atteso. Relativa → +1 e −1 (o pesi che sommano a 0), Q = spread.
- Confidenza Idzorek (forma chiusa): per ciascuna view con confidenza c∈[0,1], ricava la ω_i che
  riproduce il "tilt" desiderato verso la view; assembla Ω diagonale. Gestisci i due estremi:
  c→0 ⇒ view ignorata (ω→∞, peso 0), c→1 ⇒ view quasi vincolante (ω→0) ma EVITA la singolarità
  (clamp numerico). Documenta la formula usata con un riferimento (Idzorek 2005/2007).
- Posterior: μ_BL = [(τΣ)⁻¹ + PᵀΩ⁻¹P]⁻¹ · [(τΣ)⁻¹ Π + PᵀΩ⁻¹ Q]. Se non ci sono view, μ_BL = Π.

## CONFIGURAZIONE (nuovo file o sezione dedicata, sullo stile degli altri yaml)
- Pesi di equilibrio per asset class + regola di distribuzione dentro la classe.
- μ_target del benchmark, τ, (δ opzionale: se assente, calibrato come sopra).
- Lista di view, ognuna con: tipo (assoluta/relativa), asset/classe/regione coinvolti, valore atteso
  (annuo), confidenza 0–100%. La lista può essere VUOTA (caso di default).
- Tutto opzionale con default sensati: se il file/sezione non c'è, BL usa equilibrio neutro e zero
  view, senza errori.

## INTEGRAZIONE E PROPAGAZIONE
- Aggiungi "black_litterman" come mean_method selezionabile in estimate_parameters (default invariato
  = bayes_stein). Registralo dove serve.
- Thread dei parametri BL (config equilibrio/view) fino a profiles, core_satellite e dashboard
  (selettore del metodo di stima nella sidebar), come già si fa con gli altri metodi.
- Walk-forward: a ogni step Σ viene ri-stimata sui dati fino ad as_of, quindi Π si ricalcola da sola;
  le view restano statiche da config. Verifica che l'anti-lookahead resti intatto.
- Metadata del ParameterEstimate: registra method, δ, τ, μ_target, w_eq, Π, le view (P,Q), Ω, μ_BL e
  lo scostamento μ_BL − Π per asset (diagnostica).

## TEST (questa è la parte che mi interessa di più — fatti onesti)
1. Roundtrip di equilibrio (IL test classico di BL): se ottimizzi un MaxSharpe con μ = Π e la stessa
   Σ e SENZA vincoli stringenti, devi riottenere ≈ w_eq. Cioè i rendimenti impliciti, re-ottimizzati,
   rigenerano il portafoglio di equilibrio. Tolleranza ragionevole.
2. Nessuna view ⇒ μ_BL == Π (entro tolleranza numerica).
3. Una sola view ASSOLUTA forte (confidenza 100%) sull'asset X ⇒ μ_BL[X] ≈ valore della view;
   con confidenza bassa ⇒ μ_BL ≈ Π. Monotonìa: alzando la confidenza, μ_BL[X] si muove
   monotonicamente da Π verso la view.
4. Una view RELATIVA (X batte Y di z%) ⇒ il differenziale μ_BL[X] − μ_BL[Y] si sposta nella
   direzione e grandezza attese al crescere della confidenza.
5. μ_BL sempre finito e dentro un range sensato; Σ passata all'ottimizzatore INVARIATA.
6. Esclusione cripto rispettata: w_eq, Π e view sono definiti solo sul core tradizionale.
7. Tutti i test esistenti restano VERDI. I 5 profili restano feasible e centrano ancora il tetto di
   volatilità anche con mean_method="black_litterman" (no view).

## PRIMA / DOPO (mostramelo nel riepilogo)
- Per Bilanciato e Aggressivo: allocazione con bayes_stein vs black_litterman (zero view), e poi con
  UNA view illustrativa (scegline tu una di esempio sensata). Voglio vedere come si muovono i pesi e
  i μ per asset (storico → equilibrio → posterior con view).

## QUANDO HAI FINITO
Fermati e fammi un riepilogo: file creati/toccati; come hai definito l'equilibrio di default e i
numeri scelti (w_eq, μ_target, δ calibrato, τ); come funziona la confidenza Idzorek (formula +
riferimento); esito dei test 1–7 sopra (in particolare il roundtrip di equilibrio); il prima/dopo
delle allocazioni; conferma che i profili restano feasible e centrano la vol, che la Σ
dell'ottimizzatore è invariata e che tutti i test esistenti passano. Aspetta il mio ok prima di
committare.
```

---

## Note per te (Alessio) — non incollare in Claude Code

- **Il guadagno vero, anche senza view.** Il punto debole del modello finora era μ basato sulle medie
  storiche (rumorosissime: pochi anni di dati, stime instabili). BL, anche a zero view, sostituisce
  quelle medie con i *rendimenti di equilibrio* — un prior molto più stabile. Le view sono la
  ciliegina: ti permettono di inclinare il portafoglio col tuo giudizio in modo coerente, non "a
  mano".

- **Il test che conta davvero è il roundtrip di equilibrio** (test 1). È il controllo canonico di BL:
  se prendi i rendimenti impliciti Π e li dai in pasto all'ottimizzatore, devi riottenere il
  portafoglio di equilibrio di partenza. Se questo torna, la meccanica reverse-optimization è
  corretta. Se non torna, c'è un bug nel cuore: non andare oltre finché non torna.

- **La qualità di BL dipende TUTTA dai pesi di equilibrio che scegliamo.** Garbage in, garbage out.
  Quando Claude Code ti propone i `w_eq` di default (l'allocazione strategica neutra), guardali con
  occhio critico: rappresentano "il mercato neutrale" da cui parte tutto. È il numero più importante
  da tarare, ed è solo configurazione — possiamo cambiarlo con calma dopo aver visto l'effetto.

- **Cambierà le allocazioni raccomandate** (è voluto). I numeri nelle schede Allocazione/Confronto si
  muoveranno passando da bayes_stein a black_litterman. Verifica che abbiano senso: un BL senza view
  dovrebbe assomigliare al benchmark strategico, non a una scommessa concentrata.

- **τ, δ, μ_target sono le manopole.** τ (default 0.05) dice "quanta incertezza ha il prima di
  equilibrio"; δ è l'avversione al rischio (la calibriamo dall'equilibrio). All'inizio lasciali ai
  default e gioca semmai con le view.

- **Come si aggiunge una view**, una volta pronto: una riga in config tipo "equity Europa batte
  equity USA del 2% annuo, confidenza 60%". Da lì BL fa il resto. Comincia con una view sola per
  capire l'effetto.

- **Workflow solito**: prova in locale (default bayes_stein resta intatto, quindi nessun rischio di
  regressione), confronta black_litterman vs bayes_stein sui profili, poi commit + push. Essendo un
  cambio di CODICE, il push ricostruisce l'app online.

- Questo è un blocco grande: se preferisci, possiamo spezzarlo in due passaggi (prima
  equilibrio+Π+roundtrip, poi view+Idzorek) — dimmelo e ti preparo i due prompt separati.
