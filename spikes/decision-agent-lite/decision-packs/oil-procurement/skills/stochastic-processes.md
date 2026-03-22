# Stochastic Processes for Commodity Pricing

## Geometric Brownian Motion (GBM)

The baseline model. Price follows:
```
dS/S = μ dt + σ dW
```
**Limitation:** Assumes constant volatility, no jumps. Insufficient for geopolitical risk.

## GBM with GARCH(1,1) Volatility

Allows volatility clustering:
```
σ²(t) = ω + α·ε²(t-1) + β·σ²(t-1)
```
**Limitation:** Smooth volatility transitions. Cannot capture discrete supply shocks.

## Student-t Innovations

Replace Gaussian noise with Student-t(ν) for heavy tails:
```
z ~ t(ν) / sqrt(ν/(ν-2))    # Scaled to unit variance
log_return = (μ - σ²/2)dt + σ√dt · z
```
- ν=4: moderate fat tails (kurtosis=∞)
- ν=3: extreme tails (variance=∞ for ν≤2, so use ν≥3)
**Limitation:** Captures tail risk statistically but lacks causal structure.

## Merton Jump-Diffusion (MJD)

The preferred model for commodity supply shocks:
```
dS/S = (μ - λk)dt + σdW + JdN(λ)
```
where:
- N(λ) = Poisson process with intensity λ (jump frequency per year)
- J ~ LogNormal(μ_j, σ_j²) = random jump size
- k = E[e^J - 1] = compensator (keeps drift correct)

**Key parameters for oil under geopolitical stress:**
- λ = 2-5 (2-5 jumps per year during crisis periods)
- μ_j = 0.08-0.15 (mean log-jump: 8-16% upward bias)
- σ_j = 0.15-0.25 (jump size uncertainty)

**Why MJD wins for procurement:**
1. Separates diffusion risk from jump risk → targeted hedging
2. Jump parameters calibrate directly from historical shock data
3. The compensator ensures E[dS/S] = μdt despite jumps

## Bayesian Structural Time Series (BSTS)

Uses a latent state-space model with optional regressors:
```
y(t) = level(t) + trend(t) + seasonal(t) + β·X(t) + ε(t)
```
For commodities, X(t) can be a Geopolitical Risk Index (simulated as an OU process):
```
dG = κ(θ - G)dt + σ_g dW_g
```
**Strength:** Regime-dependent drift and volatility via the latent index.
**Limitation:** Requires real-time observation of the index for live use.

## Parameter Calibration Tips

For the U-shape in the decision analysis to appear, you need:
1. **Meaningful tail risk**: P(breach) should be 5-15% to create real penalty exposure
2. **Non-trivial hedge cost**: premium + storage + capital lockup + convex illiquidity must make Q=100% expensive
3. **The convex premium is critical**: large forward positions in crisis markets face worse fills. Model as: hedge_price * coefficient * Q, where coefficient ≈ 0.15-0.25
