# Uncertainty Quantification

## Prediction Intervals vs Confidence Intervals

- **Confidence interval**: uncertainty about the MEAN forecast
- **Prediction interval**: uncertainty about the NEXT OBSERVATION (includes observation noise)
- Prediction intervals are always wider. For decisions, you almost always want prediction intervals.

## Generating Prediction Intervals

### From Bayesian models (preferred)
Sample from the posterior predictive distribution directly:
```python
with model:
    ppc = pm.sample_posterior_predictive(trace)

forecast_samples = ppc.posterior_predictive["y_forecast"].values
lower_90 = np.percentile(forecast_samples, 5, axis=(0, 1))
upper_90 = np.percentile(forecast_samples, 95, axis=(0, 1))
```

### From ARIMA/SARIMAX
```python
forecast = model.get_forecast(steps=h)
ci = forecast.conf_int(alpha=0.10)  # 90% interval
```

### From bootstrap (any model)
```python
# Residual bootstrap for prediction intervals
residuals = y_actual - y_fitted
bootstrap_forecasts = []
for _ in range(1000):
    boot_resid = np.random.choice(residuals, size=h, replace=True)
    bootstrap_forecasts.append(point_forecast + np.cumsum(boot_resid))
lower_90 = np.percentile(bootstrap_forecasts, 5, axis=0)
upper_90 = np.percentile(bootstrap_forecasts, 95, axis=0)
```

## Fan Chart Visualization

The standard way to show forecast uncertainty:

```python
import matplotlib.pyplot as plt

fig, ax = plt.subplots(figsize=(12, 6))

# Historical
ax.plot(dates_hist, y_hist, color='black', linewidth=1.5, label='Actual')

# Forecast
ax.plot(dates_fcast, point_forecast, color='#2c3e50', linewidth=2, label='Forecast')

# Prediction intervals (nested bands)
for alpha, color_alpha in [(0.95, 0.1), (0.80, 0.2), (0.50, 0.3)]:
    lower = np.percentile(samples, (1 - alpha) / 2 * 100, axis=0)
    upper = np.percentile(samples, (1 + alpha) / 2 * 100, axis=0)
    ax.fill_between(dates_fcast, lower, upper, alpha=color_alpha,
                    color='#3498db', label=f'{int(alpha*100)}% PI')

ax.legend()
ax.set_title('Forecast with Prediction Intervals')
```

## Decision-Relevant Uncertainty Metrics

### Value at Risk (VaR)
"What's the worst-case scenario at the 5th percentile?"
```python
var_5 = np.percentile(forecast_samples, 5)
```

### Expected Shortfall / CVaR
"If we're in the worst 5% of scenarios, what's the expected value?"
```python
tail = forecast_samples[forecast_samples <= var_5]
cvar_5 = tail.mean()
```

### Probability of exceeding a threshold
"What's the probability demand exceeds 10,000 units?"
```python
prob_exceed = (forecast_samples > 10000).mean()
```

### Value of Information
"How much would reducing uncertainty be worth?"
Compare expected cost under current uncertainty vs perfect information.
This is the maximum you should pay for better data/models.

## Calibration Assessment

**Always check if your intervals are calibrated:**
```python
def check_calibration(actuals, lower, upper, nominal_coverage=0.90):
    covered = ((actuals >= lower) & (actuals <= upper)).mean()
    return {
        'nominal': nominal_coverage,
        'empirical': covered,
        'calibrated': abs(covered - nominal_coverage) < 0.10
    }
```

If systematically under-covering → widen intervals or fix model misspecification.
If systematically over-covering → intervals are conservative but not wrong.
