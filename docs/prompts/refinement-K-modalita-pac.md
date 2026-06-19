# Prompt per Claude Code — Refinement K: modalità PAC (piano di accumulo)

> Come si usa: stessa sessione di Claude Code (terminale, Opus, dentro `Portfolio-Strategy-Engine`).
> Incolla il testo dentro il riquadro. Fuori dal riquadro sono note per te.
>
> Aggiunge il PAC (versamenti periodici) ACCANTO alla somma unica esistente. Regola assoluta: NON
> modificare nulla di ciò che già funziona — il PAC è puramente additivo.

---

## ISTRUZIONI DA INCOLLARE IN CLAUDE CODE

```
Continuiamo lo stesso progetto. Tutto completo e validato fino alla dashboard online. Ora aggiungiamo
la MODALITA' PAC (Piano di Accumulo del Capitale): invece di investire tutto in un colpo (somma
unica), si versa una cifra fissa a intervalli regolari.

## REGOLA ASSOLUTA: solo aggiunte, niente modifiche al resto
Il PAC NON cambia COSA si compra: l'allocazione viene SEMPRE dal motore esistente (stessi pesi
target del profilo / core-satellite). Cambia solo QUANDO entrano i soldi. Quindi:
- NON toccare estimation/optimizer/profiles/core_satellite: restano identici.
- NON modificare la simulazione a somma unica esistente (simulate() in strategies.py) né il suo
  comportamento. Il PAC va aggiunto come funzione/percorso NUOVO, separato.
- Tutto ciò che già c'è (tab, somma unica, costi, report) deve restare uguale.

## 1. Simulazione PAC (nuova funzione, non toccare simulate())
Aggiungi una funzione nuova (es. simulate_pac in strategies.py o in un nuovo modulo) che:
- Parte da capitale iniziale 0 (o un versamento iniziale opzionale).
- A ogni data di versamento (frequenza configurabile: mensile, trimestrale, annuale) aggiunge un
  importo fisso e lo investe ai pesi target.
- Mantiene il ribilanciamento (riusa la logica/strategia esistente per riportare ai pesi target).
- Applica i costi di transazione reali della Fase 8 a OGNI versamento (spread + commissione con
  minimo). IMPORTANTE: con versamenti piccoli la commissione minima fissa pesa molto in
  percentuale — questo deve emergere nei costi, è un'informazione preziosa del PAC.
- Registra i flussi di cassa (date e importi dei versamenti) per poter calcolare l'IRR.

## 2. Metriche giuste per il PAC
Il CAGR semplice non basta perché i soldi entrano in momenti diversi. Calcola e riporta:
- Totale versato, valore finale, guadagno assoluto (valore finale − totale versato).
- IRR (rendimento money-weighted): risolvi il tasso che azzera il valore attuale dei flussi
  (versamenti negativi + valore finale positivo). Usa scipy (già dipendenza) o numpy-financial se
  preferisci, ma niente dipendenze pesanti nuove.
- Max drawdown della curva di valore del portafoglio.
- TWR (time-weighted) opzionale, per confrontabilità con la somma unica.

## 3. Confronto PAC vs somma unica (richiesto)
Aggiungi un confronto diretto sullo STESSO periodo e con lo STESSO totale di denaro:
- PAC: versa l'importo periodico lungo il periodo.
- Somma unica: investe l'INTERO totale (somma di tutti i versamenti) al giorno zero.
- Mostra le due curve di valore insieme e, affiancate, le metriche (valore finale, IRR/rendimento,
  max drawdown) delle due. Lo scopo è far vedere la differenza (di norma la somma unica finisce più
  in alto perché i soldi lavorano più a lungo, ma il PAC riduce il rischio di tempismo).

## 4. Dashboard
- Aggiungi un interruttore "Modalità: Somma unica / PAC". Default: Somma unica (comportamento
  attuale invariato).
- Se PAC: input per l'importo del versamento e selettore frequenza (mensile/trimestrale/annuale).
- Quando è attivo il PAC, mostra la curva di accumulo, le metriche PAC (totale versato, valore
  finale, IRR, max drawdown), il dettaglio costi del piano, e il confronto affiancato con la somma
  unica.
- La logica non-UI va in funzioni testabili (es. in dashboard_data.py / strategies.py); la UI le
  chiama soltanto. I numeri devono venire dal motore, nessun ricalcolo divergente.

## 5. Test
- simulate_pac: totale versato = numero versamenti × importo; con costi a zero il valore finale
  torna coi conti; l'IRR di un caso semplice noto è corretto; il PAC con un solo versamento al
  giorno zero coincide (a meno dei costi) con la somma unica.
- Confronto PAC vs somma unica coerente (stesso totale, stesso periodo).
- Tutti i test esistenti restano verdi (la somma unica non deve cambiare di una virgola).

## Quando hai finito
Fermati e fammi un riepilogo: cosa hai aggiunto (funzioni/file), come calcoli l'IRR, l'effetto dei
costi sul PAC con versamenti piccoli, un esempio numerico del confronto PAC vs somma unica, conferma
che la somma unica e tutto il resto sono INVARIATI, e che tutti i test passano. Aspetta il mio ok.
```

---

## Note per te (Alessio) — non incollare in Claude Code

- Il controllo che conta: la **somma unica deve restare identica a prima**. Quando ha finito, apri
  la dashboard in modalità "Somma unica" e verifica che i numeri siano gli stessi di adesso. Se
  cambiano, ha toccato qualcosa che non doveva.
- Guarda il **confronto PAC vs somma unica**: di norma la somma unica finisce più in alto (i soldi
  stanno investiti più a lungo). Se il PAC risultasse sistematicamente meglio su un mercato in
  salita, c'è qualcosa che non torna.
- Occhio ai **costi del PAC con versamenti piccoli**: prova un versamento da 100€/mese e guarda
  quanto pesa la commissione minima — è il vero insegnamento pratico di questa funzione.
- Come sempre: prova in locale (`streamlit run app.py`), poi quando sei contento committi e pushi.
  Ricorda che dopo il push, sull'app online, potresti dover fare il **Reboot** (la cache dati) —
  finché non sistemiamo l'auto-invalidazione, che è il prossimo-prossimo intervento in lista.

Dopo questo, in coda abbiamo: backtest configurabile, tetto per regione, auto-invalidazione cache.
Le facciamo una alla volta, verificando tra una e l'altra come sempre.
