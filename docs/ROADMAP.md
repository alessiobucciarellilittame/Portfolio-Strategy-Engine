# Portfolio Strategy Engine — Roadmap

> Documento di lavoro. Versione: bozza 0.1 — 17/06/2026
> Stato: scheletro delle fasi + **Fase 1 in dettaglio**. Le altre fasi verranno dettagliate man mano.

---

## 1. Visione del progetto

Costruire un **motore di strategia di investimento** in cui:

- **Input** = il *profilo dell'investitore* (rendimento atteso, tolleranza al rischio, orizzonte temporale, obiettivi, vincoli).
- **Output** = un **piano di investimento completo nel tempo**: allocazione multi-asset (ETF, obbligazioni, cripto, materie prime), strumenti reali in EUR, e regole di gestione (ribilanciamento, monitoraggio).

Lo stesso motore, applicato a profili diversi, genera **strategie diverse**: passive (buy & hold), attive (con ribilanciamenti periodici o a soglia) o logiche miste.

L'ottimizzatore di portafoglio (tipo Markowitz / CVaR) è solo **un componente** del sistema, non il sistema.

### A chi serve
- **Oggi**: a me, come strumento per costruire e validare strategie su profili fittizi.
- **Domani (eventuale)**: come strumento di supporto a un'attività di consulenza, con più clienti reali.

---

## 2. Principi guida (valgono per tutte le fasi)

1. **A piccoli passi verificabili.** Ogni fase produce qualcosa che *funziona ed è validato* prima di passare alla successiva. Niente "costruiamo tutto e poi vediamo".
2. **Correttezza prima di tutto.** In finanza gli errori sono silenziosi (lookahead bias, annualizzazione sbagliata, survivorship bias). Ogni modulo va validato contro un riferimento noto.
3. **Niente sguardo sul futuro (no lookahead).** Nei backtest si usano solo dati realmente disponibili in quel momento. È la regola più importante.
4. **Multi-profilo nel design, pochi profili nei test.** L'architettura accetta N profili da subito; in pratica sviluppiamo con 2-3 profili fittizi. Non costruiamo ora la gestione clienti vera (anagrafica, salvataggio, UI).
5. **Tutto guidato da configurazione.** Profilo, tipo di strategia, universo di asset, vincoli: sono parametri/oggetti, non codice da riscrivere.
6. **Fonti dati sostituibili.** Si parte gratis (yfinance) ma con un'interfaccia astratta, così domani si passa a dati a pagamento senza riscrivere il resto.
7. **Valuta base EUR, prospettiva investitore europeo.** Strumenti UCITS, conversione FX in EUR.
8. **Io sono il revisore di dominio.** Claude Code scrive ed esegue il codice; io verifico che i numeri abbiano senso. Far girare il codice ≠ codice corretto.

### Come lavoriamo con Claude Code
- Un prompt = un pezzo piccolo e ben definito (un modulo, non "tutta la piattaforma").
- Ogni prompt richiede esplicitamente: gestione degli errori, **test**, e **validazione** contro un riferimento.
- Dopo ogni pezzo: si controllano i numeri prima di proseguire.

---

## 3. Le fasi (obiettivo + scaletta)

> Nota: l'ordine è di costruzione. Alcuni layer "pratici" (es. fiscalità, strumenti reali) si raffinano più avanti, usando proxy nelle fasi iniziali.

### Fase 0 — Fondamenta & architettura
**Obiettivo:** avere uno scheletro di progetto pulito, modulare e configurabile su cui appoggiare tutto il resto.
- Struttura cartelle del progetto (dati, moduli, test, config, output).
- Repository git e gestione versioni.
- Definizione degli oggetti chiave di configurazione (es. `ProfiloCliente`, `Universo`, `Strategia`).
- Scelte tecniche di base (librerie: pandas, Riskfolio-Lib/CVXPY, ecc.) e ambiente.
- Convenzioni: logging, gestione errori, struttura dei test.

### Fase 1 — Modulo dati multi-asset ⭐ *(dettagliata sotto)*
**Obiettivo:** scaricare, pulire, validare e servire serie storiche affidabili per un universo multi-asset, in EUR, con fonte dati sostituibile.
- Definizione universo iniziale rappresentativo (ETF azionari/obbligazionari, commodity, cripto) con metadati.
- Interfaccia astratta della fonte dati + implementazione yfinance.
- Download prezzi total-return, conversione FX in EUR.
- Pulizia, allineamento calendari, gestione dati mancanti.
- Validazione automatica della qualità dei dati.
- Caching locale e output standard per le fasi successive.

### Fase 2 — Stima dei parametri (μ e Σ)
**Obiettivo:** stimare in modo robusto rendimenti attesi e matrice di covarianza, evitando l'instabilità tipica dei dati grezzi.
- Rendimenti attesi (μ): media storica + stimatori shrinkage (James-Stein, Bayes-Stein).
- Matrice di covarianza (Σ): campionaria + Ledoit-Wolf / OAS, eventuale denoising.
- Gestione di asset class con frequenze/comportamenti diversi (cripto vs bond).
- Validazione: matrici ben condizionate, valori sensati.

### Fase 3 — Motore di ottimizzazione
**Obiettivo:** dato un universo, dei parametri e dei vincoli, trovare il portafoglio ottimale.
- Più funzioni obiettivo (varianza/Markowitz, CVaR, ecc.).
- Gestione vincoli: peso min/max, long-only, vincoli per asset class/gruppo.
- Frontiera efficiente (tradeoff rischio/rendimento).
- Validazione: confronto con esempi noti delle librerie.

### Fase 4 — Profilazione cliente (profilo → parametri)
**Obiettivo:** tradurre un profilo investitore in input concreti per il motore (l'anima del progetto).
- Definizione del questionario/oggetto profilo: rischio, orizzonte, obiettivi, capacità di perdita, vincoli (es. no cripto).
- Regole di mappatura: dal profilo a obiettivo di ottimizzazione + vincoli + asset class ammesse.
- Profili fittizi di esempio (prudente, bilanciato, dinamico, ecc.).
- Validazione: profili diversi → portafogli coerentemente diversi.

### Fase 5 — Tipi di strategia & ribilanciamento
**Obiettivo:** trasformare un'allocazione statica in una strategia che vive nel tempo.
- Strategia passiva buy & hold.
- Strategia attiva: ribilanciamento periodico (es. trimestrale) e/o a soglia.
- Eventuali logiche aggiuntive (es. glide path che riduce il rischio avvicinandosi all'orizzonte).
- Strategia come "template" parametrico applicato a un profilo.

### Fase 6 — Backtest walk-forward
**Obiettivo:** verificare come si sarebbe comportata una strategia nel passato, in modo onesto.
- Motore walk-forward (stima → allocazione → tieni/ribilancia → ripeti) **senza lookahead**.
- Inclusione di costi di transazione realistici.
- Metriche: rendimento, volatilità, drawdown, Sharpe, ecc. (con annualizzazione corretta).
- Validazione: confronto con benchmark e ricostruzione di casi noti (es. 60/40).

### Fase 7 — Reportistica & piano nel tempo
**Obiettivo:** restituire un output leggibile: il "piano completo" per il profilo.
- Report di strategia: allocazione, strumenti, attese rischio/rendimento, scenario.
- Calendario di ribilanciamento e regole di monitoraggio.
- Grafici (allocazione, crescita simulata, drawdown).
- Confronto tra strategie/profili.

### Fase 8 — Layer pratici
**Obiettivo:** rendere il tutto realistico e usabile davvero.
- Mappatura asset class → strumenti reali (ETF UCITS specifici).
- Costi reali (TER, spread, commissioni) e loro impatto.
- Fiscalità italiana (tassazione su plus/dividendi, ecc.) a livello indicativo.
- Gestione cambio (FX) e integrazione con un eventuale portafoglio esistente.

### Fase 9 — Interfaccia / dashboard
**Obiettivo:** usare il tool comodamente, senza lanciare script a mano.
- Interfaccia (es. dashboard web) per inserire un profilo e vedere la strategia.
- Visualizzazione di portafogli, backtest e report.

### Fase 10 — (Futuro) Multi-cliente completo & conformità
**Obiettivo:** solo se e quando si va verso la consulenza vera.
- Gestione clienti reale (anagrafica, salvataggio, storicizzazione).
- Profilazione MiFID II / adeguatezza, trasparenza costi.
- Aspetti regolatori (Consob) e documentazione per il cliente.
- ⚠️ Questa fase apre temi legali/regolatori: va affrontata con consulenza dedicata.

---

## 4. Fase 1 in dettaglio — Modulo dati multi-asset

### 4.1 Obiettivo
Avere un modulo che, dato un universo di strumenti e un intervallo di date, restituisce **serie storiche di prezzi affidabili, pulite e validate, espresse in EUR**, pronte per essere usate dalle fasi successive. Il modulo deve essere **indipendente dalla fonte dati**: oggi yfinance, domani (eventualmente) un provider a pagamento, senza cambiare il resto del codice.

Questa fase non fa ancora ottimizzazione né strategia: costruisce le **fondamenta dati** su cui tutto poggia. Se i dati sono sbagliati, tutto il resto è teatro.

### 4.2 Scaletta operativa

**1.1 — Definire l'universo iniziale**
Una lista rappresentativa multi-asset, con metadati per ogni strumento (ticker, ISIN, nome, asset class, regione, valuta di quotazione, TER indicativo). Composizione di partenza suggerita:
- Azionario: globale (es. MSCI World), USA, Europa, mercati emergenti.
- Obbligazionario: governativo EUR, corporate, breve/lunga durata.
- Materie prime: oro / paniere commodity.
- Cripto: BTC ed ETH come asset class a sé.

Lo scopo è coprire le grandi classi di attivo, non avere centinaia di strumenti.

**1.2 — Astrazione della fonte dati (`DataProvider`)**
Definire un'interfaccia comune (es. un metodo `get_prices(tickers, start, end)`) così che yfinance sia *una* implementazione tra le tante. Domani si aggiunge un nuovo provider implementando la stessa interfaccia, senza toccare le fasi 2-9.

**1.3 — Download prezzi (provider yfinance)**
Scaricare i prezzi usando il valore **adjusted close** (corretto per dividendi e split), così da ottenere il *total return* e non un rendimento sottostimato.

**1.4 — Gestione valuta → EUR**
Gli strumenti quotati in USD (o altre valute) vanno riportati in EUR. Scaricare i tassi di cambio necessari e convertire le serie, perché la valuta base del progetto è l'euro.

**1.5 — Pulizia e allineamento**
- Allineare i calendari: le borse hanno festività diverse, le cripto quotano 24/7. Serve un calendario di riferimento comune.
- Gestire i dati mancanti in modo ragionato (forward-fill controllato, non cieco).
- Segnalare/gestire outlier evidenti (errori di feed).

**1.6 — Validazione automatica (CRITICO)**
Controlli che girano in automatico e si lamentano se qualcosa non torna:
- niente prezzi nulli, zero o negativi;
- date in ordine e senza buchi anomali;
- rendimenti giornalieri entro soglie sensate (per intercettare errori grossolani);
- copertura storica minima per ogni strumento;
- log chiaro di cosa è stato scartato, corretto o riempito.

**1.7 — Caching locale**
Salvare i dati scaricati su disco (es. formato parquet) per: non riscaricare ogni volta, evitare i limiti di richiesta di yfinance, e avere riproducibilità. Prevedere un meccanismo di aggiornamento/refresh.

**1.8 — Output standard ("contratto")**
Definire con chiarezza cosa il modulo restituisce alle fasi successive: tipicamente una tabella di prezzi puliti e una di rendimenti, con un formato fisso e documentato. Le fasi 2-9 dipenderanno da questo contratto.

**1.9 — Test e sanity check**
- Confrontare alcuni valori con fonti pubbliche (es. la chiusura nota di un ETF in una certa data).
- Verificare che i rendimenti cumulati di un indice noto siano coerenti.
- Testare il comportamento con dati mancanti o un ticker inesistente.

### 4.3 Cosa dovrà coprire il prompt per Claude Code (Fase 1)
Quando scriveremo il prompt, dovrà richiedere esplicitamente:
- interfaccia `DataProvider` astratta + implementazione yfinance separata;
- uso di adjusted close (total return);
- conversione FX in EUR;
- pulizia + allineamento calendari + gestione mancanti;
- **blocco di validazione** con controlli espliciti e log;
- caching su disco;
- definizione chiara dell'output (il "contratto");
- **test automatici** e almeno un sanity check contro un valore reale noto;
- nessun uso di dati futuri.

### 4.4 Definition of Done (Fase 1 completata quando…)
- [ ] Esiste un universo iniziale con metadati.
- [ ] Posso chiedere i prezzi di N strumenti per un intervallo e ricevere dati puliti in EUR.
- [ ] I controlli di validazione passano e segnalano i problemi quando ci sono.
- [ ] I dati sono in cache e riproducibili.
- [ ] L'output ha un formato stabile e documentato.
- [ ] Almeno un valore è stato verificato manualmente contro una fonte pubblica.
- [ ] La fonte dati è sostituibile senza toccare il resto.

---

## 5. Stato di avanzamento
- Fase 1 (dati) — completata e validata.
- Fase 2 (stima μ/Σ) — completata e validata.
- Fase 3 (ottimizzazione) — completata e validata.
- Fase 4 (profili) — completata e validata.
- Fase 5 (strategie a target fisso) — completata e validata.
- Fase 6 (backtest walk-forward) — completata e validata (test anti-lookahead seri, risultati onesti).
- Core-satellite cripto — completato (BTC come satellite opt-in, fuori dall'ottimizzatore).
- Refinement A (ri-taratura profili + tetto commodity) — completato: i 5 profili centrano il target di volatilità (5/7/10/12/14%), oro cappato al 12%.
- Refinement B (CVaR storico + risk-free configurabile) — completato.
- Refinement C (coerenza profili/core-satellite) — completato: `build_portfolio_for_profile()` esclude automaticamente le cripto dall'ottimizzazione, identico a `build_core_satellite(crypto_weight=0)`. `filter_params()` centralizzata in `estimation.py`. Equity profili ~21/38/58/72/85%, vol 5/7/10/12/14%.
- Refinement D (fix test annualizzazione) — completato: `test_annualization_synthetic_known` usava `pd.bdate_range` con 100k periodi che sfora il limite Timestamp pandas; sostituito con `RangeIndex`.
- Refinement E (docstring Sharpe) — completato: docstring di `compute_metrics()` allineata al risk-free centralizzato (non più "rf=0").
- **PROSSIMO: Fase 7 (reportistica).**

> Nota di design emersa: con le cripto fuori dall'ottimizzatore, i core dei profili alti (Bilanciato/Dinamico/Aggressivo, vol 10/12/14%) sono vicini tra loro; la differenziazione vera tra i profili più alti viene dal satellite cripto (5/10/15%).

## 6. Registro decisioni di design
Decisioni prese durante lo sviluppo, da non perdere:

- **Cripto in modalità core-satellite (IMPLEMENTATO).** Il core viene
  ottimizzato sui soli asset tradizionali (azioni, bond, oro); le cripto NON entrano
  nell'ottimizzatore. Le cripto sono un "satellite" opt-in:
  - quota decisa **caso per caso** (input esplicito a ogni costruzione di portafoglio), sempre
    limitata dal tetto cripto del profilo (Conservativo = 0%);
  - satellite = **solo BTC** come default (architettura flessibile per passare a un paniere
    BTC/ETH in futuro, da configurazione);
  - motivo: i rendimenti storici delle cripto inquinano l'ottimizzazione, e trattarle come
    scelta esplicita è più onesto e più chiaro per il cliente.

## 7. Lista delle cose da rifinire (non bloccanti)

### Fatto
- ~~Tetto massimo sulle **commodity** nei profili~~ — completato (Refinement A: oro cappato al 12%).
- ~~**CVaR storico/scenario** invece di quello parametrico gaussiano~~ — completato (Refinement B: CVaR storico come default, parametrico come confronto).
- ~~**Tasso risk-free** più realistico per il calcolo dello Sharpe~~ — completato (Refinement B: risk-free centralizzato in `src/config.py`, default 2%, supporta serie storica).

### Da fare
- ~~Layer pratici (Fase 8)~~ — completato (costi reali, fiscalità IT indicativa, FX, transizione portafoglio esistente).

### Idee / ritocchi futuri (emersi durante l'uso)
- **Periodo di backtest configurabile.** Oggi la simulazione parte da una data fissa (SIM_START = 2020-01-02). Aggiungere uno slider/parametro per scegliere da quale anno far partire il backtest (es. dal 2015), così si può vedere come sarebbe andata la strategia su finestre diverse. La stima dei parametri resta sui dati completi; cambia solo il tratto simulato.
- **Tetto per regione / per singolo strumento.** L'ottimizzatore tende a concentrarsi sui vincitori storici: con EQQQ (Nasdaq) + CSSPX (S&P 500) entrambi al tetto del 30%, l'azionario USA arriva al ~60%. Valutare un guardrail per regione (o un max_weight più basso) per evitare scommesse troppo concentrate su un'unica area.
- **Auto-invalidazione della cache dati nella dashboard.** Streamlit (`@st.cache_data`) continua a servire i dati vecchi quando il file della cache cambia, richiedendo un riavvio/clear cache manuale (in locale e in cloud). Aggiungere un "contrassegno di versione" (es. hash/mtime del file parquet) come chiave della cache, così si invalida da sola quando i dati cambiano.
