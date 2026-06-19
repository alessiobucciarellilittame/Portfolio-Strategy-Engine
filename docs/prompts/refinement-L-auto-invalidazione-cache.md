# Prompt per Claude Code — Refinement L: auto-invalidazione della cache dati nella dashboard

> Come si usa: stessa sessione di Claude Code (terminale, Opus, dentro `Portfolio-Strategy-Engine`).
> Incolla il testo dentro il riquadro. Fuori dal riquadro sono note per te.
>
> Risolve la scocciatura del "reboot ogni volta": quando i dati cambiano, la dashboard continua a
> mostrare quelli vecchi finché non la riavvii a mano (in locale e in cloud). Solo dashboard, niente
> motore.

---

## ISTRUZIONI DA INCOLLARE IN CLAUDE CODE

```
Continuiamo lo stesso progetto. Tutto completo e validato. Ora un ritocco SOLO sulla dashboard, per
risolvere un problema di cache. Non toccare il motore (estimation/optimizer/profiles/ecc.).

## IL PROBLEMA
In app.py la funzione di caricamento dati è cachata così:

    @st.cache_data(show_spinner="Caricamento dati dalla cache...")
    def _load_data(refresh: bool):
        return load_data(refresh=refresh)

La chiave della cache dipende SOLO dal parametro `refresh` (un bool). Quando il file dei dati su
disco (la cache parquet, es. cache/prices_2015-01-02_2024-12-31.parquet) CAMBIA — perché abbiamo
aggiornato i dati e fatto push — Streamlit NON se ne accorge: `_load_data(False)` continua a
restituire il DataBundle vecchio tenuto in memoria. Risultato: bisogna riavviare l'app (o fare
Reboot in cloud) ogni volta. Questo si ripercuote anche a valle, perché returns_hash/prices_hash
vengono calcolati dal bundle vecchio.

## COSA VOGLIO
Fai sì che la cache di _load_data si invalidi DA SOLA quando il file dei dati cambia.
- Aggiungi alla chiave della cache un "contrassegno di versione" del file dati: tipicamente la sua
  data di ultima modifica (os.path.getmtime) oppure un hash del contenuto del file parquet. Quando
  il file cambia, il contrassegno cambia, e Streamlit ricarica automaticamente.
- Implementazione consigliata: una piccola funzione (es. in dashboard_data.py) tipo
  data_version() che restituisce il contrassegno (mtime o hash) del/dei file di cache che load_data
  effettivamente legge (per il periodo DATA_START..DATA_END). In app.py passa questo valore come
  parametro alla funzione cachata, così entra nella chiave:

    @st.cache_data(show_spinner="...")
    def _load_data(refresh: bool, _data_version):
        return load_data(refresh=refresh)

  e la chiami con _load_data(refresh_data, data_version()).
- Mantieni funzionante la spunta "Aggiorna dati da Yahoo Finance" (refresh=True deve ancora
  forzare il ri-download).
- Gestisci con grazia il caso in cui il file di cache non esista ancora (nessun crash; il
  contrassegno può essere None o 0).

## Test
- Test della funzione data_version(): restituisce un valore stabile per lo stesso file e DIVERSO
  quando il file viene modificato (puoi simularlo toccando il mtime o riscrivendo un file
  temporaneo). Non serve testare la UI Streamlit.
- Tutti i test esistenti restano verdi.

## Verifica pratica (descrivimela, non serve tu la esegua per forza)
- Dopo la modifica: cambiando il file di cache, al successivo rerun la dashboard mostra i dati
  nuovi SENZA bisogno di riavviare/Reboot.

## Quando hai finito
Riepilogo breve: come hai costruito il contrassegno di versione, dove l'hai agganciato alla cache,
conferma che "Aggiorna da Yahoo" funziona ancora e che il motore non è stato toccato, e che i test
passano. Aspetta il mio ok.
```

---

## Note per te (Alessio) — non incollare in Claude Code

- È il ritocco che ti toglie il fastidio: dopo questo, quando aggiorni i dati e pushi, l'app
  (locale e online) si aggiorna da sola senza che tu debba fare Reboot o "Clear cache". Vale anche
  per Black-Litterman e tutto quello che verrà dopo.
- Attenzione però a una cosa: l'auto-invalidazione scatta quando cambia il **file dei dati**. Per i
  cambi di **codice** (come oggi col bug prices_hash) Streamlit Cloud ricostruisce comunque al
  push. Quindi questo risolve il caso "dati cambiati", che è quello che ti ha morso di più.
- Quando ha finito: prova in locale (`streamlit run app.py`), poi committa e pusha. Stavolta, per
  l'ultima volta, potrebbe servire un Reboot online (perché stai cambiando il codice della cache
  stessa); dopo, gli aggiornamenti di soli dati non lo richiederanno più.

Dopo questo: #7 backtest configurabile, #8 tetto per regione, poi Black-Litterman.
