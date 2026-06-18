# Prompt per Claude Code — Fase 1: Modulo dati multi-asset

> Come si usa: apri Claude Code nella cartella `Portfolio-Strategy-Engine` e incolla il testo qui sotto (la parte dentro il riquadro). Tutto ciò che sta fuori dal riquadro sono note per te, non per Claude Code.

---

## ISTRUZIONI DA INCOLLARE IN CLAUDE CODE

```
Sei il mio assistente di sviluppo per un progetto di finanza quantitativa in Python.
Stiamo costruendo, a fasi, un motore di strategie di investimento. Questa è la FASE 1:
il MODULO DATI. Non costruire ottimizzazione, profili o strategie: solo le fondamenta dati.

## Contesto e regole generali
- Lavora dentro questa cartella di progetto.
- Linguaggio: Python. Usa un ambiente virtuale e un file di dipendenze (requirements.txt o pyproject).
- Valuta base del progetto: EUR.
- Scrivi codice modulare, leggibile e commentato in italiano dove utile.
- REGOLA FONDAMENTALE: niente "lookahead". Il modulo non deve mai usare dati futuri
  rispetto alla data richiesta. Tienilo presente nel design.
- Far girare il codice NON basta: devi anche validarlo. Aggiungi test e almeno un
  controllo dei numeri contro un valore reale noto.
- Procedi a piccoli passi: prima la struttura, poi un pezzo alla volta. Alla fine
  spiegami in modo sintetico cosa hai costruito e come verificarlo.

## Struttura del progetto da creare
- Una struttura ordinata con cartelle separate per: codice sorgente, test, dati in cache,
  configurazione e metadati dell'universo.
- Un README breve che spiega come installare e come usare il modulo dati.

## Cosa deve fare il modulo dati (requisiti)

1. UNIVERSO INIZIALE
   Definisci un universo multi-asset rappresentativo (NON centinaia di strumenti), in un
   file di configurazione/metadati. Per ogni strumento salva: ticker, nome, asset class,
   regione, valuta di quotazione e (se nota) TER indicativa. Copri queste classi:
   - Azionario: globale, USA, Europa, mercati emergenti
   - Obbligazionario: governativo EUR, corporate, durate diverse
   - Materie prime: oro o paniere commodity
   - Cripto: BTC ed ETH
   Scegli tu strumenti/ticker reali e plausibili (es. ETF UCITS dove sensato), ma rendi
   l'universo facilmente modificabile da configurazione.

2. ASTRAZIONE DELLA FONTE DATI
   Crea un'interfaccia astratta per la fonte dati (es. una classe base `DataProvider`
   con un metodo tipo `get_prices(tickers, start, end)`). Poi implementa un provider
   concreto basato su yfinance. L'obiettivo è poter sostituire la fonte (domani un
   provider a pagamento) SENZA modificare il resto del codice.

3. DOWNLOAD PREZZI
   Usa il prezzo "adjusted close" (corretto per dividendi e split) per ottenere il
   total return, non un rendimento sottostimato.

4. CONVERSIONE VALUTA → EUR
   Converti in EUR le serie quotate in altre valute (es. USD), scaricando i tassi di
   cambio necessari. La valuta base è l'euro.

5. PULIZIA E ALLINEAMENTO
   - Allinea i calendari: le borse hanno festività diverse, le cripto quotano 24/7.
     Definisci un calendario di riferimento comune.
   - Gestisci i dati mancanti in modo ragionato (es. forward-fill controllato), non cieco.
   - Individua e segnala outlier evidenti (errori di feed).

6. VALIDAZIONE AUTOMATICA (parte critica)
   Aggiungi controlli automatici che segnalano i problemi con log chiari:
   - nessun prezzo nullo, zero o negativo
   - date ordinate e senza buchi anomali
   - rendimenti giornalieri entro soglie sensate (per intercettare errori grossolani)
   - copertura storica minima per ogni strumento
   - log di cosa è stato scartato, corretto o riempito

7. CACHING LOCALE
   Salva i dati scaricati su disco (es. formato parquet) per non riscaricare ogni volta,
   evitare i limiti di richiesta di yfinance e garantire riproducibilità. Prevedi un modo
   per aggiornare/rinfrescare la cache.

8. OUTPUT STANDARD ("contratto")
   Definisci con chiarezza cosa restituisce il modulo alle fasi successive: tipicamente
   una tabella di prezzi puliti in EUR e una tabella di rendimenti, in un formato fisso
   e documentato. Le fasi successive dipenderanno da questo contratto: rendilo stabile.

## Test e verifica (obbligatori)
- Scrivi test automatici per le parti chiave (pulizia, validazione, conversione FX,
  comportamento con un ticker inesistente o dati mancanti).
- Aggiungi almeno un SANITY CHECK che confronti un valore calcolato con un riferimento
  reale noto (es. la chiusura di un ETF in una certa data, o un rendimento cumulato
  plausibile di un indice), così posso fidarmi dei dati.
- Crea uno script di esempio che: prende qualche strumento dell'universo, scarica e
  pulisce i dati per un intervallo, lancia la validazione e stampa un riepilogo
  (numero di strumenti, intervallo coperto, eventuali problemi trovati).

## Cosa NON fare in questa fase
- NON costruire ottimizzazione di portafoglio, profili cliente o strategie.
- NON aggiungere interfacce grafiche.
- NON usare dati futuri.

## Quando hai finito
Fermati e fammi un riepilogo sintetico di: struttura creata, come far girare lo script
di esempio e i test, e quali controlli di validazione hai messo. Poi aspetta il mio ok
prima di passare alla fase successiva.
```

---

## Note per te (Alessio) — non incollare in Claude Code

- **Cosa controllare quando Claude Code ha finito** (sei tu il revisore di dominio):
  - Il sanity check confronta davvero un numero con un valore reale? Apri e guarda.
  - I dati sono in EUR? Verifica che un titolo USA sia stato convertito.
  - La validazione "si lamenta" davvero se metti un dato sbagliato? Provalo.
  - L'output ha un formato chiaro e stabile?
- **Se qualcosa non torna**, copiami qui l'output o l'errore: lo guardiamo insieme prima
  di andare avanti.
- **Prossimo passo dopo la Fase 1**: prompt della Fase 2 (stima di μ e Σ con shrinkage).
