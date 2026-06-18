# Prompt per Claude Code — Refinement G: fix render PDF (format specifier invalido) + test HTML

> Come si usa: stessa sessione di Claude Code (terminale, Opus, dentro `Portfolio-Strategy-Engine`).
> Incolla il testo dentro il riquadro. Fuori dal riquadro sono note per te.
>
> Bug reale emerso in verifica: render_pdf crasha quando il report include un backtest. Non l'hanno
> preso i test perché i test PDF erano skippati (weasyprint non installato) e l'esempio si fermava
> prima sull'ImportError. Da chiudere il bug E la lacuna di test.

---

## ISTRUZIONI DA INCOLLARE IN CLAUDE CODE

```
Continuiamo lo stesso progetto. La Fase 7 (reportistica) è quasi a posto: l'oggetto StrategyReport
prende i numeri dal motore correttamente (verificato, combaciano). Ma c'è un BUG nel rendering
HTML/PDF e una lacuna di test. Sistemali entrambi. Tocca solo src/reporting.py e i test.

## BUG — format specifier invalido nelle f-string
In src/reporting.py, dentro _render_profile_html(), nella sezione backtest, ci sono due f-string
malformate (intorno alle righe 499 e 503):

    {report.backtest_sharpe:.2f if report.backtest_sharpe is not None else 'n/d'}
    {report.backtest_total_costs:.4f if report.backtest_total_costs is not None else 'n/d'}

È Python non valido: NON si può mettere un if/else dentro il format specifier (:.2f). A runtime
solleva "ValueError: Invalid format specifier" e fa crashare render_pdf() ogni volta che il report
include un backtest (cioè il caso normale, vedi example_report.py).

Correggi valutando il condizionale PRIMA del formato, ad esempio:

    {(f"{report.backtest_sharpe:.2f}" if report.backtest_sharpe is not None else "n/d")}
    {(f"{report.backtest_total_costs:.4f}" if report.backtest_total_costs is not None else "n/d")}

- Cerca in TUTTO reporting.py altri casi dello stesso pattern (condizionale dentro :.Nf o simili),
  sia in _render_profile_html sia in _render_comparison_html, e correggili tutti.
- Non cambiare nient'altro della logica o del layout.

## LACUNA DI TEST — un errore di formato deve essere preso anche senza weasyprint
Il render dell'HTML (_render_profile_html / _render_comparison_html) NON richiede weasyprint: è
solo costruzione di stringa. Solo la conversione finale HTML->PDF richiede weasyprint. Quindi gli
errori di f-string si possono (e devono) testare senza dipendenze di sistema.

- Aggiungi test che invocano la costruzione dell'HTML del report (la funzione interna che produce
  la stringa HTML) con un report che INCLUDE un backtest valorizzato (backtest_cagr, sharpe,
  total_costs, max_drawdown non nulli) e con il satellite cripto. Il test deve:
  - verificare che non venga sollevata alcuna eccezione (avrebbe preso questo bug),
  - verificare che l'HTML risultante contenga i valori attesi (es. la stringa del CAGR, "n/d" nei
    casi None, ecc.).
- Aggiungi anche il caso backtest = None (sezione backtest assente) per coprire entrambi i rami.
- Se la funzione HTML è "privata" (underscore), va benissimo testarla direttamente
  dall'interno del modulo.
- I test PDF veri (con weasyprint) restano skip-if-unavailable come ora: ma il render HTML va
  testato SEMPRE.

## Verifica
- Esegui tutti i test: i nuovi test HTML passano, i 181 originali + quelli di reporting restano
  verdi.
- Se possibile nel tuo ambiente, genera davvero un PDF con backtest (example_report.py) e conferma
  che non crasha e che il file non è vuoto. Se weasyprint non è installabile da te, dillo: il test
  HTML è comunque la garanzia che il bug è chiuso.

## Quando hai finito
Riepilogo breve: le righe corrette (e se ne hai trovate altre simili), i test HTML aggiunti, e
conferma "tutti i test verdi". Aspetta il mio ok.
```

---

## Note per te (Alessio) — non incollare in Claude Code

- Il bug era latente per due motivi insieme: i test PDF si auto-skippano se weasyprint non c'è, e
  sul tuo Mac l'esempio moriva prima sull'ImportError di weasyprint. Bastava una delle due
  protezioni mancanti e non lo vedevi. L'ho beccato installando weasyprint e generando un PDF vero
  con il backtest dentro.
- La lezione di metodo: il render HTML non ha bisogno di librerie di sistema, quindi va testato
  sempre. Dopo questo refinement, un errore di formato nel template viene preso anche senza
  weasyprint installato.
- Quando ha finito, controlla che il test nuovo esista e che esiti senza skip:
  ```
  pytest tests/test_reporting.py -v
  pytest tests/ -q
  ```
- Per generare i PDF veri sul Mac ti servono le librerie di sistema:
  `brew install pango gdk-pixbuf libffi` e poi `pip install weasyprint`.

Chiuso questo, la Fase 7 è davvero completa: numeri onesti (già verificati), PDF che si genera, e
test che proteggono il template. Da lì si passa alla Fase 8 (layer pratici).
