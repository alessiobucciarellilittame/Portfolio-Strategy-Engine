# Prompt per Claude Code — Black-Litterman: verifiche prima del commit

> Come si usa: stessa sessione di Claude Code, dentro `Portfolio-Strategy-Engine`, DOPO aver
> implementato Black-Litterman (BL non ancora committato).
> Incolla il testo dentro il riquadro. Fuori dal riquadro sono note per te (Alessio).
>
> Non aggiunge feature nuove: chiude i tre dubbi da revisore prima di dare l'ok — (1) i profili sotto
> BL centrano ancora i target di vol? (2) BL regge fuori campione nel walk-forward vs Bayes-Stein?
> (3) la convenzione delle view (rendimento totale vs eccesso) è coerente con Π+rf? Più una
> quantificazione della concentrazione USA.

---

## ISTRUZIONI DA INCOLLARE IN CLAUDE CODE

```
Prima di committare Black-Litterman voglio chiudere alcuni controlli da revisore. Sono soprattutto
DIAGNOSTICHE e una piccola messa a punto. Non cambiare il default (bayes_stein resta tale), non
toccare la Σ dell'ottimizzatore, non rompere i test esistenti. Procedi e poi fermati per il mio ok.

## 1. VOL REALIZZATA PER PROFILO SOTTO BL (centrano il target o restano sotto?)
Per tutti e 5 i profili, a parità di tutto, stampa una tabella di confronto bayes_stein vs
black_litterman (ZERO view):
- vol REALIZZATA, rendimento atteso, Sharpe;
- ripartizione equity / bond / commodity (%);
- esposizione per regione, in particolare USA (%).
Poi rispondi esplicitamente: ogni profilo CENTRA ancora il suo target di vol (5 / 7 / 10 / 12 / 14%)
oppure resta SOTTO il tetto? Se qualche profilo finisce sotto target con BL, spiega PERCHÉ (es. μ più
piatto ⇒ il vincolo di vol non satura più allo stesso modo) e dimmi se serve ritarare qualcosa
(senza farlo ora: solo diagnosi e proposta). La monotonìa del rischio tra profili deve restare.

## 2. WALK-FORWARD OUT-OF-SAMPLE: BL (zero view) vs BAYES-STEIN
Questo è il test che conta davvero. Lancia il backtest walk-forward già esistente, IDENTICO per i due
metodi (stesso periodo, stessa finestra di ri-stima, stesso anti-lookahead, stessi costi di
transazione, stesso universo, stesse strategie di ribilanciamento). Niente cherry-picking.
- Falli girare almeno su Bilanciato e Aggressivo (meglio tutti e 5 se non è troppo lento).
- Metriche a confronto: CAGR, vol annua, Sharpe, max drawdown, turnover medio e costi totali.
- Mostra le due equity curve (o i dati per ricostruirle).
- Commenta ONESTAMENTE: BL fa meglio, uguale o peggio fuori campione? L'attesa è che BL abbia Sharpe
  in-sample più basso ma drawdown/robustezza migliori out-of-sample; verifica se è davvero così sui
  NOSTRI dati, senza abbellire il risultato. Se BL non aiuta out-of-sample, dimmelo chiaro.

## 3. CONVENZIONE DELLE VIEW (coerenza con Π + rf)
Abbiamo stabilito che μ_BL = Π + rf, cioè Π è il PREMIO AL RISCHIO (eccesso su risk-free) e si somma
rf per avere il rendimento totale atteso. Verifica e rendi COERENTE la convenzione delle view
assolute:
- Una view assoluta deve essere espressa come RENDIMENTO TOTALE atteso (es. "equity USA: 9% annuo
  totale"), e internamente confrontata con Π+rf — NON con Π da solo. Controlla che oggi sia così; se
  la view viene confrontata con Π (eccesso) mentre l'utente la pensa come totale, c'è uno sfasamento
  di livello pari a rf.
- Documenta la convenzione nel commento del config delle view e in un test dedicato: una view
  assoluta pari esattamente a (Π+rf)[X] con confidenza 100% NON deve muovere μ_BL[X] (perché
  coincide già con l'equilibrio). Se questo test non passa, la convenzione è sfasata: correggila.
- Le view relative (X − Y) sono spread e non risentono di rf: verificalo e lascia un test che lo
  conferma.

## 4. CONCENTRAZIONE USA (collegamento al tetto per regione)
Quantifica, per ogni profilo, l'esposizione USA sotto bayes_stein vs black_litterman (zero view).
Ipotesi da verificare: BL, distribuendo l'equity in modo più uniforme tra le aree, abbassa da solo la
concentrazione USA (che con bayes_stein arrivava a ~60% su Bilanciato/Aggressivo). Dammi i numeri:
se l'ipotesi regge, lo annoto come motivo per cui il tetto-per-regione diventa molto meno necessario
con BL come default.

## QUANDO HAI FINITO
Fermati e fammi un riepilogo con: la tabella vol-realizzata per profilo (punto 1) con la risposta
secca "centra/non centra il target"; la tabella del walk-forward BL vs Bayes-Stein (punto 2) con il
tuo giudizio onesto out-of-sample; l'esito del controllo convenzione view + il test aggiunto
(punto 3); la tabella esposizione USA (punto 4). Conferma che default, Σ e test esistenti sono
intatti. Aspetta il mio ok prima di committare qualsiasi cosa.
```

---

## Note per te (Alessio) — non incollare in Claude Code

- **Il punto 2 è quello decisivo.** Lo Sharpe in-sample più basso di BL non è un problema: è il prezzo
  della robustezza. La domanda vera è "fuori campione, nel walk-forward onesto, BL regge?". Se sì
  (Sharpe simile ma drawdown/turnover migliori), BL merita di diventare il default. Se BL out-of-sample
  va peggio anche lì, allora il valore di BL è soprattutto "diversificazione e controllo via view",
  non performance — e lo terremmo come opzione, non come default. In entrambi i casi avrai un numero
  su cui decidere, non una sensazione.

- **Sul punto 1**: con BL i μ sono più piatti, quindi è plausibile che qualche profilo "alto" non
  spinga più fino al tetto di vol come faceva con Bayes-Stein. Non è un bug: è il modello che è meno
  aggressivo. Però è bene saperlo, perché cambia il significato dei profili. Se serve, si ritara
  dopo (solo configurazione).

- **Sul punto 3**: è una pignoleria da revisore ma conta. Se le view assolute fossero confrontate con
  Π (eccesso) mentre tu le pensi come rendimento totale, ogni tua view sarebbe sistematicamente
  "alta di un 2%" (il rf). Il test che ho chiesto (view = equilibrio ⇒ nessun movimento) è il modo
  pulito per blindare la convenzione.

- **Sul punto 4**: se i numeri confermano che BL abbassa da solo l'USA, abbiamo la risposta al dubbio
  che avevi lasciato in sospeso sul tetto-per-regione (refinement-N): con BL default, quel guardrail
  diventa quasi ridondante. Una decisione in meno da portarti dietro.

- Come sempre: è tutto a default invariato, quindi puoi far girare queste diagnostiche senza rischio.
  Si committa solo dopo che i numeri ti convincono.
