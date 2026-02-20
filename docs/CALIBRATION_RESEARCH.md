# Calibration Research

This document outlines the research and rationale for ensemble forecast calibration, which is planned for implementation after collecting sufficient prediction data.

## Why Calibration Matters

### The Problem: Ensemble Underdispersion

GFS ensemble forecasts (and most NWP ensembles) are systematically **underdispersed** - they don't capture the full range of possible outcomes. This means:

- Probability estimates are **overconfident**
- When the ensemble says 80% chance, reality might be 65%
- Kelly criterion amplifies miscalibration into position sizing errors

### Example Impact

| Raw Ensemble | Actual Freq | Overconfidence | Kelly Impact |
|-------------|-------------|----------------|--------------|
| 80% | 65% | +15% | 2.3x overbet |
| 60% | 50% | +10% | 1.5x overbet |
| 40% | 35% | +5% | 1.2x overbet |

A 15% miscalibration at 80% probability leads to dramatically oversized positions.

## Calibration Methods Compared

### 1. Isotonic Regression (Recommended)

**What it does:** Non-parametric monotonic mapping from raw probabilities to calibrated probabilities.

**Pros:**
- No distributional assumptions
- Learns arbitrary calibration curves
- Available in scikit-learn (`sklearn.isotonic.IsotonicRegression`)
- Simple to implement and interpret

**Cons:**
- Requires 500-1000+ samples per probability bin
- Can overfit with small datasets

**Implementation:**
```python
from sklearn.isotonic import IsotonicRegression

# Training
ir = IsotonicRegression(out_of_bounds='clip')
ir.fit(raw_probs, outcomes)

# Inference
calibrated_prob = ir.predict([raw_prob])[0]
```

### 2. Ensemble Model Output Statistics (EMOS)

**What it does:** Fits a distributional model (typically Gaussian) to ensemble spread and bias.

**Pros:**
- Meteorologically principled
- Can correct both bias and spread
- Well-established in weather forecasting

**Cons:**
- Requires domain expertise to implement correctly
- More complex than isotonic regression
- Assumptions may not hold for all weather regimes

### 3. Bayesian Model Averaging (BMA)

**What it does:** Weights ensemble members by historical performance.

**Pros:**
- Theoretically elegant
- Can capture multi-modal distributions

**Cons:**
- Computationally expensive
- Requires careful prior selection
- Overkill for binary bucket predictions

### 4. Platt Scaling

**What it does:** Logistic regression on raw probabilities.

**Pros:**
- Simple parametric approach
- Works well for binary classification

**Cons:**
- Assumes sigmoid relationship
- May not capture complex miscalibration patterns

## Recommended Approach

**Start with Isotonic Regression** because:
1. No assumptions about calibration curve shape
2. Proven effective for probability calibration
3. Easy to implement with scikit-learn
4. Can be replaced with EMOS later if needed

## Data Requirements

### Minimum Viable Calibration

| Metric | Requirement | Rationale |
|--------|-------------|-----------|
| Total samples | 500+ | Statistical power |
| Per-bin samples | 30+ | Reliable frequency estimates |
| Date range | 30+ days | Capture seasonal variation |
| Cities | 3+ | Reduce geographic bias |

### Optimal Calibration

| Metric | Requirement | Rationale |
|--------|-------------|-----------|
| Total samples | 2000+ | Robust non-parametric fit |
| Per-bin samples | 100+ | Tight confidence intervals |
| Date range | 90+ days | Full seasonal coverage |
| Lead times | 1-3 days | Separate calibration per lead |

## Implementation Plan

### Phase 1: Data Collection (Current)

1. Record ALL bucket predictions via `PredictionTracker`
2. Store raw ensemble probabilities
3. Record actual outcomes after resolution

### Phase 2: Analysis (After 30+ Days)

1. Plot calibration curves (reliability diagrams)
2. Calculate Brier skill score
3. Identify systematic biases per city/lead-time

### Phase 3: Calibration Implementation (After 60+ Days)

1. Fit isotonic regression models
2. Per-city and per-lead-time calibration
3. A/B test calibrated vs uncalibrated signals
4. Monitor performance improvement

## Validation

### Reliability Diagram

Plot predicted probability (x-axis) vs observed frequency (y-axis). Perfect calibration = diagonal line.

### Brier Score

```
BS = (1/n) * Σ(forecast - outcome)²
```

Lower is better. Decompose into:
- **Reliability:** How well probabilities match frequencies
- **Resolution:** How informative the forecasts are
- **Uncertainty:** Inherent unpredictability

### Expected Calibration Error (ECE)

```
ECE = Σ(bin_size/n) * |avg_confidence - avg_accuracy|
```

Measures average calibration gap across probability bins.

## References

1. Gneiting, T., & Raftery, A. E. (2007). "Strictly Proper Scoring Rules, Prediction, and Estimation." JASA.
2. Hamill, T. M., & Colucci, S. J. (1997). "Verification of Eta–RSM Short-Range Ensemble Forecasts." Monthly Weather Review.
3. Raftery, A. E., et al. (2005). "Using Bayesian Model Averaging to Calibrate Forecast Ensembles." Monthly Weather Review.
4. Wilks, D. S. (2018). "Enforcing Calibration in Ensemble Postprocessing." Quarterly Journal of the Royal Meteorological Society.

## Code Location

- Prediction tracking: `producer/signal_producer/services/prediction_tracker.py`
- Calibration data query: `PredictionTracker.get_calibration_data()`
- Calibration summary: `PredictionTracker.get_calibration_summary()`

## Future Considerations

1. **Per-city calibration:** Different stations may have different biases
2. **Seasonal calibration:** Summer vs winter may require different curves
3. **Lead-time calibration:** 1-day vs 3-day forecasts have different error characteristics
4. **Online learning:** Update calibration as new data arrives
