# Decision Theory for Procurement

## Expected Utility Framework

The buyer's total cost for hedge fraction Q:

```
C(Q) = C_hedge(Q) + C_spot(Q) + C_penalty(Q)
```

### Hedge Cost (deterministic)
```
C_hedge = Q · V · (S₀·premium + storage + capital_lockup + convex_premium(Q))
```
where:
- V = total volume
- S₀ = current spot price
- premium = forward contract markup (crisis premium: 8-12%)
- storage = $/bbl/week × average weeks stored
- capital_lockup = S₀·premium × annual_rate × (T/52)
- convex_premium(Q) = S₀·premium × coefficient × Q (grows with position size)

The **convex premium** is the key ingredient: it makes full hedging expensive, creating the right side of the U-shape. Economically justified: large forward positions in illiquid crisis markets face progressively worse fills.

### Spot Cost (stochastic)
```
C_spot = (1-Q) · V/T · Σ S(t)    over all time steps
```
The buyer purchases the unhedged volume evenly across weeks at the realized spot price.

### Catastrophic Penalty
```
C_penalty = 1{max(S) > threshold} · (1-Q) · V · penalty_per_bbl
```
If the spot price exceeds the threshold on ANY week, a massive penalty applies to the entire unhedged volume. This represents production halts, emergency procurement, or contract penalties.

## Optimal Hedge Ratio

Q* = argmin E[C(Q)]

The expectation is over all Monte Carlo paths. At Q*:
- Marginal reduction in penalty exposure = marginal increase in hedge cost
- This is the Bayesian optimal balance under the modeled uncertainty

## Value of Information (Opportunity Delta)

```
VoI = max(C(0), C(1)) - C(Q*)
```

This quantifies how much the decision analysis is worth: the cost savings from choosing Q* over the naive worst-case strategy. If VoI is small, the decision doesn't matter much. If VoI is large, getting Q* right is critical.

## Risk Metrics for the Plot

**Expected Total Cost curve** — the primary output. Should form a U-shape.

**±1σ band** — shows cost variability. Wide at low Q (exposed to spot risk), narrow at high Q (mostly deterministic).

**Cost decomposition** — stacked area chart showing how the three components trade off:
- Blue: hedge cost (linear + convex in Q)
- Yellow: spot cost (linear decrease in Q)
- Red: penalty (decreases with Q as less volume is exposed)
