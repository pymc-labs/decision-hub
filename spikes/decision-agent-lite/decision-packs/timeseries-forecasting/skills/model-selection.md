# Model Selection Guide

## Decision Tree for Model Selection

```
Is the series stationary?
├── Yes → ARIMA / ETS / VAR
│   ├── Strong autocorrelation? → ARIMA(p,0,q)
│   ├── Multiple series? → VAR or Bayesian hierarchical
│   └── Simple patterns? → ETS (Holt-Winters)
│
├── No (unit root) → Difference first, then:
│   ├── Seasonal? → SARIMA(p,d,q)(P,D,Q,s)
│   ├── Trend + seasonal? → Prophet-style or BSTS
│   └── Regime changes? → Markov-switching or BSTS with changepoints
│
└── Inconclusive → Try multiple approaches in parallel
```

## Model Catalog

### ARIMA / SARIMAX
**When:** Clear autocorrelation structure, stationary (after differencing)
**Strengths:** Well-understood, fast, good for short-term
**Weaknesses:** Linear, poor with structural breaks, point estimates only
**Implementation:** `statsmodels.tsa.statespace.SARIMAX` or `pmdarima.auto_arima`

```python
from pmdarima import auto_arima
model = auto_arima(y, seasonal=True, m=12, stepwise=True,
                   suppress_warnings=True, error_action='ignore')
```

### ETS (Exponential Smoothing)
**When:** Trend and/or seasonality, no complex autocorrelation
**Strengths:** Simple, interpretable, handles multiplicative seasonality
**Weaknesses:** No exogenous variables, limited uncertainty quantification
**Implementation:** `statsmodels.tsa.holtwinters.ExponentialSmoothing`

### Bayesian Structural Time Series (BSTS)
**When:** Need uncertainty quantification, structural breaks, exogenous regressors
**Strengths:** Full posterior, handles missing data, regime changes, causal impact
**Weaknesses:** Slower, requires prior specification, MCMC convergence
**Implementation:** PyMC with custom model

```python
import pymc as pm

with pm.Model() as bsts:
    # Local linear trend
    sigma_level = pm.HalfNormal("sigma_level", sigma=0.1)
    sigma_trend = pm.HalfNormal("sigma_trend", sigma=0.01)

    level = pm.GaussianRandomWalk("level", sigma=sigma_level, shape=T)
    trend = pm.GaussianRandomWalk("trend", sigma=sigma_trend, shape=T)

    # Seasonal component (Fourier)
    # ...

    mu = level + trend + seasonal
    sigma_obs = pm.HalfNormal("sigma_obs", sigma=0.5)
    y_obs = pm.Normal("y_obs", mu=mu, sigma=sigma_obs, observed=y)
```

### Prophet-style Decomposition
**When:** Long series with multiple seasonalities, holidays, changepoints
**Strengths:** Handles holidays, robust to missing data, interpretable components
**Weaknesses:** Not truly Bayesian in practice, can overfit changepoints
**Implementation:** Can implement in PyMC for proper uncertainty

## Ensemble Methods

When multiple models pass validation, ensemble them:

1. **Simple average** — robust baseline
2. **Inverse-variance weighting** — weight by 1/MSE on holdout
3. **Stacking** — train a meta-model on holdout predictions

Ensembles almost always beat individual models on out-of-sample accuracy.

## Information Criteria

For comparing models fit on the SAME data:
- **AIC** — penalizes complexity, asymptotically efficient
- **BIC** — stronger complexity penalty, consistent
- **WAIC** — Bayesian analogue, use with PyMC models (`az.waic(trace)`)
- **LOO-CV** — leave-one-out via PSIS (`az.loo(trace)`)

**Never compare AIC/BIC across different differencing orders** — the likelihoods aren't comparable.
