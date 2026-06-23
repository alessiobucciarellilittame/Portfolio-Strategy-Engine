# Prompt per Claude Code — Satellite azionario (singole azioni opt-in)

> Come si usa: stessa sessione di Claude Code, dentro `Portfolio-Strategy-Engine`.
> Incolla il testo dentro il riquadro. Fuori dal riquadro sono note per te (Alessio).
>
> Obiettivo: poter aggiungere SINGOLE AZIONI al portafoglio senza romperne la matematica. Le azioni
> singole NON entrano nell'ottimizzatore (stessa ragione delle cripto: pochi dati per troppi parametri,
> rischio specifico, serve analisi fondamentale che il motore non fa). Diventano un SECONDO satellite,
> scelto da te, cappato per profilo, aggiunto sopra il core di ETF. Riusa il meccanismo core-satellite
> che già esiste per le cripto: NON inventarne uno nuovo.

---

## ISTRUZIONI DA INCOLLARE IN CLAUDE CODE

```
Continuiamo lo stesso progetto. Voglio aggiungere un SATELLITE AZIONARIO: la possibilità di tenere
singole azioni come quota esplicita, opt-in e cappata, FUORI dall'ottimizzatore — esattamente come
già facciamo con le cripto (BTC) in core_satellite.py. Generalizza il meccanismo esistente invece di
duplicarlo. Procedi a piccoli passi, non rompere il satellite cripto (deve restare identico), default
invariati, e fermati alla fine per il mio ok.

## PRINCIPIO (identico alle cripto)
- Le singole azioni sono una nuova asset class NON ottimizzabile (es. asset_class: "stock"). Come le
  cripto, vengono ESCLUSE dall'ottimizzazione del core (filter_params) e riaggiunte come satellite
  esplicito.
- La quota del satellite azionario la decide l'utente, limitata da un tetto per profilo (come il
  tetto crypto). La sizing NON la fa l'algoritmo: è una scommessa consapevole e contenuta.
- Combinazione: combined = core * (1 − quota_crypto − quota_stock) + satellite_crypto + satellite_stock.

## 1. GENERALIZZA IL SATELLITE (core_satellite.py)
Oggi build_core_satellite gestisce un solo satellite (crypto). Generalizzalo per gestire N "sleeve"
satellite, ognuno legato a una asset class non-ottimizzabile, con la sua quota e il suo tetto:
- Mantieni la firma e il comportamento attuali per le cripto (retro-compatibilità totale: chiamate
  esistenti e test devono dare risultati IDENTICI).
- Aggiungi il supporto a uno sleeve "stock": parametro per la quota azionaria richiesta e per la
  composizione del satellite ({ticker: peso_relativo}, sizing per convinzione).
- Il filtro del core deve escludere TUTTE le classi non-ottimizzabili (crypto E stock), non solo le
  cripto. Generalizza get_crypto_tickers / CRYPTO_ASSET_CLASS in un concetto di "classi satellite"
  (es. SATELLITE_ASSET_CLASSES = {"crypto", "stock"}), tenendo le cripto come caso particolare.
- Clamp di ogni quota al tetto del rispettivo profilo; valida che i ticker satellite esistano nei
  params e appartengano alla classe giusta (un ticker "stock" nel satellite crypto va rifiutato e
  viceversa).
- Le statistiche combinate si calcolano sui params COMPLETI (μ/Σ includono le azioni), come già fai:
  così l'effetto sul rischio/rendimento del portafoglio è trasparente, anche se le azioni non sono
  nell'ottimizzatore.

## 2. UNIVERSO E PROFILI (config)
- universe.yaml: documenta come si aggiunge una singola azione (asset_class: "stock", regione,
  valuta). Aggiungi 1-2 esempi reali con storia LUNGA (dal ~2015) per non accorciare la finestra di
  stima — stessa lezione di ETH (vedi nota sotto). NON aggiungere titoli con IPO recente di default.
- profiles.yaml: aggiungi a ogni profilo un tetto stock in group_limits, sullo stile del tetto crypto.
  Default ragionevoli e TARABILI (sono guardrail): proposta conservativo 0%, moderato 5%, bilanciato
  10%, dinamico 15%, aggressivo 20%. Scegli numeri che non rendano nulla infeasible e che restino
  prudenti (è rischio specifico, va tenuto piccolo). profile_to_constraints deve ESCLUDERE anche il
  vincolo "stock" dall'ottimizzatore, come già fa con crypto.

## 3. PROPAGAZIONE
- Thread del nuovo sleeve fino a dashboard_data e app, accanto a quello cripto. Default = 0 (nessuna
  azione singola) per retro-compatibilità.
- walk-forward / strategie: combined_weights resta il target; le azioni satellite sono tenute a quota
  fissa come le cripto. Verifica che l'anti-lookahead e la simulazione reggano.

## 4. DASHBOARD (app.py)
- Aggiungi un pannello "Satellite azionario (azioni singole)" accanto a quello cripto: l'utente
  sceglie i ticker azionari (tra quelli classificati "stock" nell'universo) e la quota totale (slider,
  cappato dal tetto del profilo). Mostra l'allocazione combinata con le azioni incluse.
- Etichetta chiara: avviso che le azioni singole sono rischio concentrato, scelto dall'utente, fuori
  dall'ottimizzazione.

## 5. TEST
- Satellite crypto invariato: stessi risultati di prima (regressione zero).
- Satellite stock: quota rispettata e cappata al tetto del profilo; le azioni NON entrano nel core
  (il core resta di soli ETF tradizionali); pesi combinati sommano a 1.
- Due satelliti insieme (crypto + stock): combined = core*(1−qc−qs) + sat_crypto + sat_stock, somma 1,
  nessun peso negativo.
- Validazione: ticker stock nel satellite crypto rifiutato (e viceversa); quota oltre il tetto
  clampata con messaggio.
- Conservativo con tetto stock 0% → quota azionaria forzata a 0.
- Tutti i test esistenti restano verdi.

## QUANDO HAI FINITO
Fermati e fammi un riepilogo: come hai generalizzato il satellite (file toccati, concetto di classi
satellite); i tetti stock di default per profilo; come si aggiunge un'azione all'universo; un esempio
numerico con un satellite azionario (es. Dinamico con 10% su 1-2 titoli) che mostri core + satellite +
combinato e le stats; esito dei test inclusa la conferma che il satellite cripto è identico a prima.
Aspetta il mio ok prima di committare.
```

---

## Note per te (Alessio) — non incollare in Claude Code

- **Cosa ottieni**: il portafoglio diventa core di ETF (ottimizzato, la base solida) PIÙ un satellite
  di azioni che scegli tu, cappato. È il modello core-satellite vero: disciplina sulla base,
  convinzioni personali in una quota contenuta. Le cripto e le azioni convivono come due satelliti
  separati, ognuno col suo tetto.

- **Perché restano fuori dall'ottimizzatore** (te lo ricordo perché è la decisione chiave): l'algoritmo
  non sa dimensionare bene i singoli titoli, e un'azione porta rischio specifico che la
  diversificazione non cancella. Quindi la quota la decidi tu, consapevolmente, e il motore la tiene
  cappata. È onesto.

- **Attenzione alla storia dei titoli** (la lezione di ETH): se aggiungi un'azione con IPO recente,
  accorci la finestra di stima per TUTTI gli strumenti (il dropna taglia tutti alla storia più corta).
  Per questo ho chiesto titoli con storia lunga negli esempi. Se vuoi un titolo "giovane", se ne può
  parlare, ma sappi che è un compromesso sui dati.

- **Il lavoro che resta tuo**: il motore ti dà la cornice (quanta quota, con che tetto, e l'effetto sul
  rischio del portafoglio combinato). QUALI azioni mettere nel satellite è giudizio tuo — e le singole
  azioni vogliono un'analisi che questo motore non fa (valutazioni, bilanci, se un titolo è caro). Non
  metterci roba "a sensazione": il satellite è piccolo apposta, ma resta rischio concentrato.

- **Occhio alla somma dei satelliti**: crypto e stock hanno tetti separati, ma insieme erodono il core.
  Se metti 10% cripto + 15% azioni, il 25% del portafoglio è fuori dall'ottimizzatore. Tienilo
  presente: più satellite = meno disciplina, più scommessa.

- Come sempre: default a zero (nessun satellite azionario se non lo chiedi), quindi nessun rischio di
  regressione. Prova in locale, poi commit + push.
