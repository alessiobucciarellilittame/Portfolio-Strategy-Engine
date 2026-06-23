# Prompt per Claude Code — Black-Litterman: equilibrio market-cap + confronto a tre

> Come si usa: stessa sessione di Claude Code, dentro `Portfolio-Strategy-Engine`, dopo le verifiche
> BL (ancora non committate).
> Incolla il testo dentro il riquadro. Fuori dal riquadro sono note per te (Alessio).
>
> Il problema emerso: l'equilibrio equal-weight dentro la classe equity dà agli USA solo 2/7 del peso,
> anche se valgono ~60-70% del mercato azionario globale. È una view anti-USA implicita, ed è il motivo
> per cui BL ha perso contro Bayes-Stein nel walk-forward 2020-2024. Qui rendiamo l'equilibrio
> market-cap (un prior neutrale più difendibile) e rifacciamo il confronto walk-forward A TRE:
> Bayes-Stein vs BL-equalweight vs BL-marketcap. Niente commit: è ancora diagnostica.

---

## ISTRUZIONI DA INCOLLARE IN CLAUDE CODE

```
Continuiamo su Black-Litterman (non ancora committato). Abbiamo scoperto che l'equilibrio equal-weight
dentro la classe equity sottopesa strutturalmente gli USA (2/7 dell'equity) rispetto al loro peso reale
nel mercato globale (~60-70%): è una view anti-USA implicita che ha penalizzato BL nel walk-forward.
Ora rendiamo l'equilibrio MARKET-CAP e confrontiamo a tre. È DIAGNOSTICA: non cambiare il default
(bayes_stein), non committare, fermati per il mio ok.

## 1. DISTRIBUZIONE DENTRO LA CLASSE: AGGIUNGI L'OPZIONE MARKET-CAP
Oggi i pesi di equilibrio sono distribuiti equal-weight dentro ogni classe. Rendi la distribuzione
CONFIGURABILE in config/black_litterman.yaml con un campo tipo within_class_weighting: "equal" |
"market_cap". Mantieni "equal" funzionante (è il comportamento attuale, non romperlo). Aggiungi
"market_cap" e rendilo il default del nuovo confronto.

NON cambiare lo split macro tra classi (equity 60% / bond 35% / commodity 5% resta fisso): vogliamo
isolare UNA variabile sola, cioè la distribuzione DENTRO l'equity. Dillo nel commento del config.

## 2. GESTISCI L'OVERLAP DEGLI ETF (punto delicato, fallo con cura)
L'universo equity ha un fondo WORLD (SWDA, MSCI World, già cap-weighted: ~70% USA) PIÙ fondi regionali
che si sovrappongono ad esso (CSSPX=S&P500, EQQQ=Nasdaq, SXR8/SMEA=Europa, SJPA=Giappone, EIMI=EM).
Un equilibrio market-cap che pesasse tutti e 7 per capitalizzazione conterebbe gli USA DUE VOLTE
(dentro World e dentro S&P/Nasdaq). Per evitarlo, usa questo approccio pulito e documentalo:

- Equilibrio equity NEUTRALE = solo i due fondi BROAD non sovrapposti: SWDA (World, sviluppati) +
  EIMI (EM), con split ~market-cap developed/emerging (default ~88% World / 12% EM, configurabile).
- I fondi REGIONALI/settoriali (CSSPX, EQQQ, SXR8, SMEA, SJPA) ricevono peso di equilibrio ZERO: NON
  fanno parte del "mercato neutrale", sono strumenti per esprimere tilt/view.
- IMPORTANTE: peso di equilibrio zero NON significa esclusi dall'ottimizzazione. Con Π = δ·Σ·w_eq, ogni
  asset (anche a w_eq=0) riceve comunque un rendimento implicito sensato via la sua covarianza col
  mercato. L'ottimizzatore può ancora allocarli. Verifica che sia così.
- Risultato atteso: dato che SWDA è ~70% USA, l'esposizione USA implicita nell'equilibrio torna
  realistica (~55-65% dell'equity) invece del ~17-25% dell'equal-weight.

Per i bond e le commodity lascia pure equal-weight (o uno split govt-heavy ragionevole per i bond):
non sono il punto, ma rendili coerenti col meccanismo.

Tutto il resto di BL (calibrazione δ, τ, Π, posterior, Idzorek) resta IDENTICO: cambia solo come si
costruisce w_eq.

## 3. MOSTRAMI L'EQUILIBRIO PRIMA DI OTTIMIZZARE
Stampa i pesi di equilibrio w_eq e la quota USA implicita SOTTO i due schemi (equal vs market_cap),
così vedo il prior in sé, non solo l'output ottimizzato.

## 4. CONFRONTO WALK-FORWARD A TRE (il cuore)
Rifai il backtest walk-forward, IDENTICO in tutto (stesso periodo, finestra di ri-stima, anti-lookahead,
costi di transazione, universo, strategie), per TRE metodi:
- Bayes-Stein (BS)
- BL equal-weight (BL-EW)  -> il BL di prima
- BL market-cap (BL-MC)    -> il nuovo
Su tutti e 5 i profili se non è troppo lento (almeno Bilanciato, Dinamico, Aggressivo).
Metriche a confronto: CAGR, vol annua, Sharpe, max drawdown, turnover medio, costi totali. E, per ogni
profilo/metodo, l'esposizione USA media.

## 5. GIUDIZIO ONESTO (mi serve la verità, non il lieto fine)
Rispondi esplicitamente:
- BL-MC si colloca TRA BS e BL-EW come performance, come mi aspetto? Di quanto chiude il gap con BS?
- BL-MC mantiene i vantaggi di BL (turnover più basso, più diversificazione, allocazione stabile)?
- L'esposizione USA di BL-MC è ragionevole (via di mezzo tra il ~60% di BS e il ~20% di BL-EW)?
- Conclusione secca: con l'equilibrio market-cap, BL diventa un candidato sensato a default, oppure no?
  Senza abbellire: se BS resta meglio anche così sul nostro campione, dillo (ricordando che il campione
  2020-2024 è comunque favorevole a chi insegue gli USA, quindi il giudizio resta condizionato al
  campione).

## 6. TEST
- Il roundtrip di equilibrio regge anche con i pesi market-cap (MaxSharpe con μ=Π+rf ⇒ ≈ w_eq market-cap).
- No-view ⇒ μ_BL = Π+rf, per entrambi gli schemi di pesatura.
- Entrambe le modalità (equal, market_cap) coperte da test; "equal" continua a dare i risultati di prima.
- I 5 profili restano feasible e centrano il tetto di vol con BL-MC.
- Tutti i test esistenti restano verdi. Confermami anche che i 7 test "skip" di prima sono quelli
  gated dalla rete (--network) e non test BL silenziati.

## QUANDO HAI FINITO
Fermati e fammi un riepilogo: come hai reso configurabile la distribuzione e come hai gestito l'overlap
(World+EM core, regionali a peso zero); la quota USA dell'equilibrio equal vs market-cap (punto 3); la
tabella walk-forward a tre con il tuo giudizio onesto (punti 4-5); esito dei test (punto 6) incluso il
chiarimento sui 7 skip. Conferma che default, Σ e test esistenti sono intatti. Aspetta il mio ok prima
di committare.
```

---

## Note per te (Alessio) — non incollare in Claude Code

- **Cosa stiamo correggendo, in una riga**: l'equal-weight diceva implicitamente "USA come Giappone come
  Europa come EM". Il market-cap dice "USA pesa quanto pesa davvero nel mondo (~60% dell'azionario)".
  Il secondo è un prior neutrale molto più difendibile; il primo era una scommessa anti-USA travestita
  da neutralità.

- **Come abbiamo evitato il doppio conteggio** (il punto tecnico delicato): abbiamo un fondo World che
  *già contiene* gli USA, più i fondi USA separati. Se li pesassimo tutti per cap, conteremmo gli USA
  due volte. La soluzione pulita: il "mercato neutrale" è solo World + EM (i due mattoni che non si
  sovrappongono), e i fondi regionali restano lì come strumenti per le view, non come parte
  dell'equilibrio. Elegante e corretto.

- **Cosa mi aspetto dai numeri**: BL-MC dovrebbe cadere *tra* BS e BL-EW. Probabilmente NON batterà BS
  su 2020-2024 (niente batte "tutto sugli USA" in quel periodo), ma dovrebbe chiudere gran parte del
  gap mantenendo turnover più basso e meno concentrazione. Se è così, abbiamo un BL onesto e
  difendibile, non una caricatura.

- **La decisione sul default resta tua e resta in parte una scommessa sul futuro**: BS = "gli USA
  continueranno a dominare"; BL-MC = "parto dal mercato globale e mi muovo solo con view esplicite".
  Il backtest non può deciderlo per noi (abbiamo solo dati di bull market USA dal 2015). Ma dopo questo
  giro avrai il quadro completo per scegliere con cognizione.

- Resta tutto a default invariato: nessun rischio a far girare la diagnostica. Si committa solo quando
  i numeri ti convincono — e a quel punto decidiamo insieme se BL-MC diventa il default o resta opzione.
