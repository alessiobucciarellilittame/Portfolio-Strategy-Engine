# Prompt per Claude Code — Refinement I: espansione universo (più azionario + obbligazionario)

> Come si usa: stessa sessione di Claude Code (terminale, Opus, dentro `Portfolio-Strategy-Engine`).
> Incolla il testo dentro il riquadro. Fuori dal riquadro sono note per te.
>
> Aggiunge strumenti al paniere per dare più scelta all'ottimizzatore. Il punto delicato è la
> FINESTRA DI STIMA: strumenti con storia corta accorciano il periodo comune per tutti. Per questo
> il prompt chiede di verificare la storia di ogni nuovo ticker.

---

## ISTRUZIONI DA INCOLLARE IN CLAUDE CODE

```
Continuiamo lo stesso progetto. Tutto completo e validato fino alla Fase 9 (dashboard online).
Ora ESPANDIAMO L'UNIVERSO degli strumenti per dare più scelta all'ottimizzatore. NON cambiare la
logica del motore: si tocca la configurazione dell'universo e si rigenera la cache dati.

## Cosa aggiungere
Aggiungi a config/universe.yaml nuovi ETF UCITS, quotati in EUR (per coerenza con la valuta base),
in due classi:

Azionario (esposizioni NUOVE, non duplicati di MSCI World/S&P500/Euro Stoxx già presenti):
- Nasdaq-100 (taglio tech/crescita) — es. Invesco EQQQ.
- Giappone (regione oggi assente) — es. un iShares/Xtrackers MSCI Japan.
- Europa ampio (MSCI Europe, oltre alle sole big cap di Euro Stoxx 50).

Obbligazionario (sfumature nuove sul lato difensivo):
- Inflation-linked EUR (obbligazioni legate all'inflazione) — es. iShares € Inflation Linked Govt.
- Governativo EUR lunga durata (15-30 anni) — più sensibile ai tassi.
- High yield EUR (credito ad alto rendimento) — es. iShares € High Yield Corp Bond.

Per ciascuno scegli il ticker Yahoo Finance corretto, con i metadati richiesti dallo schema
esistente (ticker, name, asset_class, region, currency, ter).

## VINCOLO CRITICO — storia dei dati (la finestra di stima)
La stima dei parametri usa il periodo in cui TUTTI gli strumenti hanno dati (la pipeline allinea e
fa dropna). Quindi uno strumento con storia corta ACCORCIA la finestra comune per tutti.
- Per OGNI nuovo ticker, prima di aggiungerlo, VERIFICA scaricando i dati che:
  1. il ticker esista e scarichi davvero da Yahoo Finance;
  2. abbia storia che parte almeno dal 2015 (inizio della cache attuale).
- Se un candidato non scarica o è troppo giovane (storia che inizia dopo il 2015), NON aggiungerlo:
  proponi un'alternativa equivalente con storia più lunga, oppure segnalalo chiaramente e lascialo
  fuori. Meglio meno strumenti ma con finestra di stima lunga, che tanti strumenti che ci fanno
  perdere gli anni 2015-2017.
- Riportami, per ogni nuovo strumento, la data di inizio dei dati effettivi.

## Rigenera la cache dati
- Dopo aver aggiornato universe.yaml, rigenera la cache dei prezzi (la pipeline, con refresh) per il
  periodo 2015-01-02 / 2024-12-31, così la cache contiene anche i nuovi strumenti. La dashboard e
  l'app online leggono da lì.
- Mantieni il formato e il nome file della cache esistente (cache/prices_2015-01-02_2024-12-31.parquet)
  così il resto del codice e la dashboard continuano a funzionare senza modifiche.

## Validazione e test
- Esegui la validazione dati (deve passare: niente prezzi nulli/negativi, copertura ok) e segnala
  eventuali avvisi sui nuovi strumenti.
- Tutti i test esistenti devono restare verdi.
- Mostra il PRIMA/DOPO: per un paio di profili (es. Bilanciato e Aggressivo), quanti e quali
  strumenti usa l'ottimizzatore adesso rispetto a prima, per dimostrare che la scelta più ampia si
  riflette nei portafogli.
- Conferma la finestra di stima risultante (data inizio / fine): se non è più 2015, dimmi perché
  (quale strumento l'ha accorciata).

## Nessuna modifica alla UI
La dashboard legge l'universo in modo dinamico: non dovrebbe servire toccare app.py. Verifica solo
che la dashboard giri ancora (i nuovi strumenti compaiono da soli nelle tabelle).

## Quando hai finito
Fermati e fammi un riepilogo: gli strumenti aggiunti con la loro data di inizio dati, quelli
eventualmente SCARTATI perché troppo giovani (con motivazione), la finestra di stima finale, il
prima/dopo delle allocazioni, e conferma che validazione e test passano. Aspetta il mio ok.
```

---

## Note per te (Alessio) — non incollare in Claude Code

- Il punto su cui devi vigilare (sei il revisore di dominio): la **finestra di stima**. Quando ha
  finito, controlla che ti dica da che anno parte la stima. Se è rimasta al 2015, ottimo. Se si è
  accorciata (es. parte dal 2018), vuol dire che un nuovo strumento ha storia corta e ha tagliato
  gli anni vecchi per tutti: valuta se quello strumento vale la perdita di storia, altrimenti
  diglielo di toglierlo.
- Controlla il **prima/dopo** delle allocazioni: l'obiettivo era dare più scelta, quindi ti aspetti
  di vedere qualche strumento nuovo entrare nei portafogli (o almeno che l'ottimizzatore li
  consideri). Se nessuno entra mai, sono doppioni inutili e tanto vale toglierli.
- Occhio ai **TER**: i nuovi ETF (soprattutto Nasdaq, Giappone, high yield) costano un po' di più
  dei tuoi ETF core super-economici. È normale, ma si rifletterà nella scheda Costi.

### Quando è fatto e verificato — mandalo online
Questa volta cambiano anche i **dati** (la cache), non solo il codice. Quindi, come per la
correzione di prima:
1. Apri GitHub Desktop → vedrai modificati `universe.yaml` e il file della cache `.parquet`.
2. Commit (es. "Espansione universo: +azionario +obbligazionario") → Push origin.
3. L'app online si rigenera da sola e userà il nuovo paniere.

Prima però provala in locale (`streamlit run app.py`) e guarda nella scheda Allocazione e Confronto
Profili che i nuovi strumenti compaiano e abbiano senso.
