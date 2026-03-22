# Time Series Diagnostics

## Stationarity Testing

Always run BOTH tests — they have different null hypotheses:

**ADF (Augmented Dickey-Fuller):**
- H0: unit root exists (non-stationary)
- Reject at p < 0.05 → evidence of stationarity
- Use `statsmodels.tsa.stattools.adfuller`

**KPSS:**
- H0: series is stationary
- Reject at p < 0.05 → evidence of non-stationarity
- Use `statsmodels.tsa.stattools.kpss`

Interpretation matrix:
| ADF | KPSS | Conclusion |
|-----|------|------------|
| Reject | Don't reject | Stationary |
| Don't reject | Reject | Non-stationary — difference |
| Both reject | Both reject | Trend-stationary — detrend |
| Neither reject | Neither reject | Inconclusive — try both approaches |

## Seasonality Detection

Use `statsmodels.tsa.seasonal.STL` for robust decomposition:
- Set `period` based on data frequency (7 for daily, 12 for monthly, 52 for weekly)
- Check seasonal component amplitude vs residual amplitude
- If seasonal/residual ratio > 2, seasonality is strong

For unknown periodicity, use the periodogram:
```python
from scipy.signal import periodogram
freqs, power = periodogram(y, detrend='linear')
dominant_period = 1 / freqs[np.argmax(power[1:]) + 1]
```

## Residual Analysis

A well-specified model should have residuals that are:
1. **Uncorrelated** — ACF within confidence bands, Ljung-Box p > 0.05
2. **Homoscedastic** — constant variance over time (plot residuals vs time)
3. **Approximately normal** — for valid prediction intervals (QQ plot)

```python
from statsmodels.stats.diagnostic import acorr_ljungbox
lb_test = acorr_ljungbox(residuals, lags=[10, 20], return_df=True)
```

## Bayesian Convergence Diagnostics

For PyMC / MCMC models:

```python
import arviz as az
summary = az.summary(trace, var_names=["~log_likelihood"])
```

**Hard requirements:**
- R-hat < 1.1 for ALL parameters (< 1.01 preferred)
- ESS bulk > 400 (> 100 per chain minimum)
- ESS tail > 400
- Divergences < 1% of total samples

**Soft checks:**
- Trace plots should look like "hairy caterpillars" (good mixing)
- Rank plots should be uniform across chains
- Energy plot: marginal energy and energy transition distributions should overlap

## Forecast Evaluation Metrics

**Point forecast accuracy:**
- RMSE: √(mean(errors²)) — penalizes large errors
- MAE: mean(|errors|) — robust to outliers
- MAPE: mean(|errors/actuals|) — scale-free, but undefined for zero actuals
- sMAPE: mean(2|errors|/(|actuals|+|forecast|)) — symmetric version

**Prediction interval calibration:**
- Compute empirical coverage: what fraction of actuals fall within the stated interval?
- Target: 90% PI should contain ~90% of holdout values
- If coverage < 70%, intervals are too narrow (overconfident)
- If coverage > 98%, intervals are too wide (uninformative)

**Cross-validation for time series:**
- NEVER use random k-fold — it leaks future information
- Use expanding window or sliding window CV
- Report mean and std of metrics across folds
