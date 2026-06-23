# Portfolio Strategy Engine

Motore di strategia di investimento: dal profilo dell'investitore a un portafoglio ottimizzato con backtest walk-forward. Universo multi-asset in EUR (ETF UCITS azionari, obbligazionari, oro, cripto).

Pipeline completa: dati -> stima parametri (mu/Sigma) -> ottimizzazione -> profilazione cliente -> strategie di ribilanciamento -> backtest walk-forward, con architettura core-satellite per le cripto. Stima mu: Bayes-Stein (default, shrinkage storico) o Black-Litterman (equilibrio market-cap + view soggettive opzionali con confidenza Idzorek).

## Installazione

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Uso rapido

```python
from datetime import date
from src.pipeline import run_pipeline
from src.estimation import estimate_parameters
from src.profiles import build_all_profiles

bundle = run_pipeline(start=date(2015, 1, 2), end=date(2024, 12, 31))
params = estimate_parameters(bundle.returns, mean_method="bayes_stein", cov_method="ledoit_wolf")
ac_map = bundle.universe["asset_class"].to_dict()

results = build_all_profiles(params, horizon_years=5, asset_class_map=ac_map)
for r in results:
    s = r.portfolio.stats
    print(f"{r.profile_name:15s}  vol={s['volatility']:.2%}  ret={s['expected_return']:.2%}")
```

## Test

```bash
# Test unitari (senza rete)
pytest tests/

# Test completi (con download da Yahoo Finance)
pytest tests/ --network
```

## Struttura

```
src/
  pipeline.py         Pipeline dati e contratto DataBundle
  data_provider.py    Interfaccia astratta + YFinanceProvider
  universe.py         Caricamento universo da config
  fx.py               Conversione valutaria -> EUR
  cleaning.py         Pulizia, allineamento, outlier
  validation.py       Controlli automatici qualita' dati
  cache.py            Caching Parquet locale
  estimation.py       Pipeline stima parametri e ParameterEstimate
  mean_estimators.py  Stimatori mu (historical, James-Stein, Bayes-Stein)
  black_litterman.py  Black-Litterman: equilibrio market-cap + view soggettive (Idzorek)
  cov_estimators.py   Stimatori Sigma (sample, Ledoit-Wolf, OAS)
  optimizer.py        Ottimizzazione portafoglio (MinVar, MaxSharpe, MaxReturn, MinCVaR)
  frontier.py         Frontiera efficiente
  constraints.py      Vincoli di portafoglio (long-only, gruppi, tetti)
  profiles.py         Profilazione cliente (5 profili, vol ceiling come leva)
  strategies.py       Strategie di ribilanciamento (buy&hold, periodico, a soglia)
  walkforward.py      Backtest walk-forward con ri-stima anti-lookahead
  core_satellite.py   Core tradizionale + satellite cripto opt-in
  config.py           Configurazione centralizzata (risk-free rate)
  costs.py            Costi reali, fiscalita', FX, transizione (Fase 8)
  reporting.py        Reportistica e piano PDF (Fase 7)
  dashboard_data.py   Logica non-UI per la dashboard (Fase 9)
app.py                Dashboard Streamlit (Fase 9)
config/
  universe.yaml       Universo strumenti (10 ETF UCITS + cripto)
  profiles.yaml       Profili investitore (conservativo -> aggressivo)
  black_litterman.yaml Configurazione Black-Litterman (equilibrio, view, tau)
  costs_tax.yaml      Configurazione costi e fiscalita'
tests/                Test automatici
cache/                Dati scaricati (Parquet)
scripts/              Script di esempio
output/               Grafici generati
docs/                 Documentazione e roadmap
```

## Script di esempio

```bash
python scripts/example.py                  # Dati: download e validazione universo
python scripts/example_estimation.py       # Stima parametri: mu/Sigma con shrinkage
python scripts/example_optimization.py     # Ottimizzazione: frontiera efficiente e portafogli
python scripts/example_profiles.py         # Profili: 5 livelli di rischio, vol target vs realizzata
python scripts/example_strategies.py       # Strategie: buy&hold vs ribilanciamento, equity curves
python scripts/example_walkforward.py      # Walk-forward: backtest con ri-stima rolling
python scripts/example_core_satellite.py   # Core-satellite: core tradizionale + satellite cripto
python scripts/example_ritocchi.py         # CVaR storico vs parametrico, risk-free configurabile
python scripts/example_black_litterman.py # Black-Litterman: equilibrio + view assolute/relative
```

## Profili investitore

5 profili calibrati con vol ceiling come leva primaria:

| Profilo       | Vol target | Equity | Bond  | Commodity | Crypto (satellite) |
|---------------|-----------|--------|-------|-----------|--------------------|
| Conservativo  | 5%        | ~21%   | ~67%  | ~12%      | 0%                 |
| Moderato      | 7%        | ~38%   | ~50%  | ~12%      | max 2%             |
| Bilanciato    | 10%       | ~58%   | ~30%  | ~12%      | max 5%             |
| Dinamico      | 12%       | ~72%   | ~16%  | ~12%      | max 10%            |
| Aggressivo    | 14%       | ~85%   | ~3%   | ~12%      | max 15%            |

Le cripto non entrano nell'ottimizzatore: sono gestite come satellite esplicito (architettura core-satellite).

## Universo strumenti

Definito in `config/universe.yaml`. Copre: azionario globale/USA/Europa/EM, obbligazionario EUR, oro, BTC, ETH. Facilmente modificabile.

## Dashboard

Interfaccia web Streamlit che avvolge il motore. Input nella sidebar (profilo, orizzonte, cripto, strategia, capitale), output in 6 tab (allocazione, rischio/rendimento, backtest, costi/tasse, confronto profili, PDF).

### Lancio in locale

```bash
streamlit run app.py
```

La dashboard carica i dati dalla cache locale (`cache/*.parquet`). Se la cache non esiste, eseguire prima `python scripts/example.py` per scaricare i dati, oppure attivare la spunta "Aggiorna dati da Yahoo Finance" nella sidebar.

### Pubblicazione su Streamlit Community Cloud

1. Pushare il repository su GitHub (con la cartella `cache/` e i file parquet).
2. Andare su [share.streamlit.io](https://share.streamlit.io) e collegare il repository.
3. Il file `packages.txt` installa le dipendenze di sistema necessarie per la generazione PDF (weasyprint). Se il PDF non e' necessario, la dashboard funziona anche senza.
4. Entry point: `app.py`.
