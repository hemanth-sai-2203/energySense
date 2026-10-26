# Phase 2: Forecasting Engine & Model Evaluation Report
**EnergySense / GridSense Platform**  
*Evaluation Date: October 2026 | Dataset Range: 2013-01-01 to 2024-04-28*

---

## 1. Executive Summary & Benchmark Reproduction

Phase 2 established a leakage-safe, zero-external-dependency time-series forecasting pipeline for Indian national power metrics:
1. **Primary Target**: Daily National Energy Met (`energy_met_mu`, MU)
2. **Secondary Target**: Daily National Peak Met (`peak_met_mw`, MW)

All learned transformations (feature scalers, regression weights, decision trees) were fit strictly on the **Training Set (2013–2021)**. Hyperparameter tuning and model architecture decisions were frozen exclusively on the **Validation Set (2022)** before evaluating once on the **Final Holdout Set (2023-01-01 through 2024-04-28)**.

### Benchmark Reproduction Audit
Before training any machine learning models, we investigated the reported exploratory benchmark of **MAE ~89.92 MU (2.08% MAPE)** on the holdout period:

| Evaluation Method | Evaluated Days | Excluded Dates / Handling | Day-1 Persistence MAE (MU) | Day-1 Persistence RMSE (MU) | Day-1 Persistence MAPE (%) | Seasonal-Naive $t-7$ MAE (MU) | Notes |
| :--- | :---: | :--- | :---: | :---: | :---: | :---: | :--- |
| **Method A: Naive Row Index Shift** | 483 | None (shifts row $i-1$) | **89.92** | 117.09 | **2.08%** | N/A | Reproduces the exact reported prior benchmark. Unsafe across calendar gaps (shifts across 2023-03-30). |
| **Method B: Strict Calendar $t-1$** | 482 | Excludes 2023-03-31 ($t-1$ missing) | **89.61** | 116.72 | **2.07%** | N/A | Strictly calendar-correct Day-1 persistence. |
| **Method C: Common Valid Set ($t-1$ & $t-7$)** | 481 | Excludes 2023-03-31 and 2023-04-06 | **89.74** | 116.84 | **2.07%** | **182.20** | Fair, identical-date baseline comparison for both persistence and seasonal-naive. |

**Conclusion on Baseline**: The prior report's 89.92 MU MAE is verified and reproduced. It was computed using a naive row-shift ($i-1$) on 483 days. On a strict calendar-lag basis, Persistence achieves **89.61 MU**, while Seasonal-Naive ($t-7$) achieves **182.20 MU** (4.22% MAPE).

---

## 2. Leakage-Safe Feature Engineering

To guarantee zero data leakage across chronological splits:
- **Exact Calendar Lags**: For forecast target day $t$, candidate lags are derived strictly via datetime arithmetic: $t-h, t-h-1, t-7, t-14, t-21, t-28$.
- **No Artificial Imputation**: Missing dates in history are never forward-filled or interpolated for model training. If a required exact lag is absent, the observation is omitted from the sample matrix.
- **Robust Rolling Windows**: Rolling 7-day and 28-day historical averages require $\ge 5$ and $\ge 20$ valid observations respectively, strictly bounded by $t-h$.
- **Calendar & Seasonality Features**: Day-of-week one-hot encoding (Mon–Sat, Sun reference), 1st and 2nd harmonic Fourier terms ($\sin/\cos$ on day-of-year), and normalized secular trend.
- **Strictly Out-of-Sample Scaler**: `StandardFeatureScaler` fits means and standard deviations exclusively on training data ($2013-2021$). Validation and holdout data use the frozen training parameters.
- **Zero UTCI Dependency**: Excluded from primary production pipeline because the 2023–2024 holdout lacks real-time UTCI weather observations.

---

## 3. Validation Performance & Model Selection (2022)

The 2022 validation year ($N=338$ complete feature dates) served as the decision gatekeeper.

### Validation Results (Day-1 Ahead, $H=1$)
| Target | Candidate Model | Hyperparameters / Setup | Val MAE | Val RMSE | Val MAPE (%) | Improvement vs Persistence | Selection Decision |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| **Energy Met (MU)** | Day-1 Persistence | $y_{t-1}$ baseline | 83.52 MU | 108.57 MU | 2.08% | 0.0% | Baseline |
| | Seasonal-Naive | $y_{t-7}$ baseline | 132.14 MU | 183.04 MU | 3.28% | -58.2% | Baseline |
| | **Ridge Regressor** | $\alpha = 0.01$, L2 Closed-Form | **54.56 MU** | **76.92 MU** | **1.35%** | **+34.7%** | **SELECTED (Active Model)** |
| | Compact Decision Tree | Max Depth = 5, Split = 20 | 99.92 MU | 128.32 MU | 2.43% | -19.6% | Rejected (high variance) |
| | Ridge + COVID Feature | Binary 2020 lockdown indicator | 54.43 MU | 76.92 MU | 1.35% | +34.8% | Rejected (see COVID analysis) |
| | Ridge Excl. 2020 Lockdown | Train set excludes Mar-May 2020 | 54.33 MU | 76.66 MU | 1.34% | +35.0% | Rejected (omits shock training) |
| **Peak Met (MW)** | Day-1 Persistence | $y_{t-1}$ baseline | 4,084.07 MW | 5,442.80 MW | 2.08% | 0.0% | Baseline |
| | Seasonal-Naive | $y_{t-7}$ baseline | 5,629.37 MW | 7,700.35 MW | 2.86% | -37.8% | Baseline |
| | **Ridge Regressor** | $\alpha = 0.01$, L2 Closed-Form | **2,518.74 MW** | **3,550.95 MW** | **1.28%** | **+38.3%** | **SELECTED (Active Model)** |
| | Compact Decision Tree | Max Depth = 6, Split = 20 | 4,755.08 MW | 5,829.98 MW | 2.37% | -16.4% | Rejected (high variance) |

### Investigation of COVID-19 Lockdown Structural Break
The prompt required testing whether a lockdown indicator improves validation performance before adopting it:
1. Adding `is_lockdown_2020` (1 for March 24, 2020 to May 31, 2020, 0 otherwise) changes the 2022 validation MAE by only **0.13 MU** (54.43 vs 54.56 MU), because outside 2020 the feature is permanently 0.
2. Dropping the lockdown months from training changes 2022 validation MAE by **0.23 MU** (54.33 vs 54.56 MU).
3. **Decision**: We do **NOT** add a permanent lockdown feature to the active production model. Forcing an arbitrary dummy indicator that is zero across the entire forecast future risks false degrees of freedom with no physical basis.

### Fallback Gatekeeper Decision
- Rule: If ML Validation MAE $\ge$ Persistence Validation MAE, fallback activates and Persistence is retained.
- For Energy: Ridge MAE (54.56 MU) beats Persistence (83.52 MU) by **34.7%**.
- For Peak: Ridge MAE (2,518.74 MW) beats Persistence (4,084.07 MW) by **38.3%**.
- **Outcome**: Fallback not triggered. Ridge Regressor is certified and promoted as the production model.

---

## 4. Final Holdout Evaluation (2023–2024, Frozen Models)

The selected models were evaluated once on the unseen holdout set (2023-01-01 to 2024-04-28, $N=477$ complete feature dates).

### Summary Holdout Metrics ($H=1$)
| Target Metric | Baseline Model | Baseline MAE | Selected Ridge MAE | Selected Ridge RMSE | Selected Ridge MAPE (%) | MAE Reduction vs Baseline |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| **National Daily Energy Met** | Day-1 Persistence | 90.09 MU | **63.54 MU** | **84.93 MU** | **1.46%** | **29.48% MAE Reduction** |
| | Seasonal-Naive ($t-7$) | 181.52 MU | **63.54 MU** | **84.93 MU** | **1.46%** | **65.00% MAE Reduction** |
| **National Daily Peak Met** | Day-1 Persistence | 4,788.80 MW | **3,384.48 MW** | **4,722.03 MW** | **1.58%** | **29.33% MAE Reduction** |
| | Seasonal-Naive ($t-7$) | 8,520.63 MW | **3,384.48 MW** | **4,722.03 MW** | **1.58%** | **60.28% MAE Reduction** |

### Holdout Error Breakdown by Year
| Target | Partition | Sample Count | Persistence MAE | Ridge Regressor MAE | Ridge RMSE | Ridge MAPE (%) | MAE Reduction |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Energy (MU)** | Full Year 2023 | 358 | 93.08 MU | 66.00 MU | 87.11 MU | 1.52% | **29.1%** |
| | Jan–Apr 2024 | 119 | 81.10 MU | 56.14 MU | 78.01 MU | 1.26% | **30.8%** |
| **Peak (MW)** | Full Year 2023 | 358 | 4,820.46 MW | 3,452.50 MW | 4,730.66 MW | 1.63% | **28.4%** |
| | Jan–Apr 2024 | 119 | 4,693.53 MW | 3,179.85 MW | 4,695.97 MW | 1.43% | **32.2%** |

### Seasonal Stress Periods (Holdout)
| Target | Season / Stress Regime | Dates Evaluated | Persistence MAE | Ridge Regressor MAE | Ridge RMSE | Ridge MAPE (%) | MAE Reduction |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Energy (MU)** | Summer Heatwaves (May–Jun) | 61 | 112.30 MU | 88.28 MU | 112.17 MU | 1.97% | **21.4%** |
| | Winter Baseline (Dec–Jan) | 93 | 68.21 MU | 43.27 MU | 58.24 MU | 1.06% | **36.6%** |
| **Peak (MW)** | Summer Heatwaves (May–Jun) | 61 | 5,053.97 MW | 4,020.30 MW | 5,542.51 MW | 1.91% | **20.5%** |
| | Winter Baseline (Dec–Jan) | 93 | 3,836.43 MW | 2,418.60 MW | 3,435.34 MW | 1.13% | **37.0%** |

*Insight*: During peak summer heatwaves, non-linear weather extremes and air conditioning load surges cause higher variance (Ridge MAE rises to 88.28 MU), but Ridge still outperforms Persistence by > 21%. During stable winter baselines, Ridge reduces MAE to 43.27 MU (1.06% MAPE).

---

## 5. Multi-Horizon Forecasting ($H = 1 \dots 7$ Days Ahead)

To address the prompt's instruction ("don't assume a model that wins at day one also wins at day seven"), we trained and evaluated direct multi-step forecasting models for each horizon $h \in \{1, 2, 3, 4, 5, 6, 7\}$:

### National Daily Energy Met (`energy_met_mu`, MU)
| Forecast Horizon | Persistence ($y_{t-h}$) MAE | Seasonal-Naive ($y_{t-7}$) MAE | Direct Ridge MAE | Direct Ridge RMSE | Direct Ridge MAPE (%) | Improvement vs Persistence | Improvement vs Seasonal-Naive |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Day 1 Ahead** ($H=1$) | 90.09 MU | 181.52 MU | **63.54 MU** | 84.93 MU | 1.46% | **+29.48%** | **+65.00%** |
| **Day 2 Ahead** ($H=2$) | 134.54 MU | 181.48 MU | **107.48 MU** | 139.58 MU | 2.46% | **+20.11%** | **+40.78%** |
| **Day 3 Ahead** ($H=3$) | 158.52 MU | 181.75 MU | **132.94 MU** | 171.36 MU | 3.05% | **+16.13%** | **+26.86%** |
| **Day 4 Ahead** ($H=4$) | 171.06 MU | 181.79 MU | **152.22 MU** | 192.92 MU | 3.48% | **+11.02%** | **+16.27%** |
| **Day 5 Ahead** ($H=5$) | 181.41 MU | 181.68 MU | **168.16 MU** | 209.10 MU | 3.84% | **+7.31%** | **+7.45%** |
| **Day 6 Ahead** ($H=6$) | 180.53 MU | 181.40 MU | **179.41 MU** | 220.52 MU | 4.09% | **+0.62%** | **+1.09%** |
| **Day 7 Ahead** ($H=7$) | 181.14 MU | **181.14 MU** | 186.73 MU | 228.41 MU | 4.25% | **-3.09%** | **-3.09%** |

### National Daily Peak Met (`peak_met_mw`, MW)
| Forecast Horizon | Persistence ($y_{t-h}$) MAE | Seasonal-Naive ($y_{t-7}$) MAE | Direct Ridge MAE | Direct Ridge RMSE | Direct Ridge MAPE (%) | Improvement vs Persistence | Improvement vs Seasonal-Naive |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Day 1 Ahead** ($H=1$) | 4,788.80 MW | 8,520.63 MW | **3,384.48 MW** | 4,722.03 MW | 1.58% | **+29.33%** | **+60.28%** |
| **Day 2 Ahead** ($H=2$) | 6,461.33 MW | 8,524.63 MW | **5,169.26 MW** | 6,851.03 MW | 2.41% | **+20.00%** | **+39.36%** |
| **Day 3 Ahead** ($H=3$) | 7,495.92 MW | 8,540.44 MW | **6,318.52 MW** | 8,154.36 MW | 2.95% | **+15.71%** | **+26.02%** |
| **Day 4 Ahead** ($H=4$) | 8,121.92 MW | 8,540.87 MW | **7,177.10 MW** | 9,189.54 MW | 3.35% | **+11.63%** | **+15.97%** |
| **Day 5 Ahead** ($H=5$) | 8,683.48 MW | 8,540.62 MW | **7,900.03 MW** | 9,950.97 MW | 3.68% | **+9.02%** | **+7.50%** |
| **Day 6 Ahead** ($H=6$) | 8,876.85 MW | 8,526.87 MW | **8,445.32 MW** | 10,496.73 MW | 3.92% | **+4.86%** | **+0.96%** |
| **Day 7 Ahead** ($H=7$) | 8,503.65 MW | **8,503.65 MW** | 8,799.88 MW | 10,872.51 MW | 4.08% | **-3.48%** | **-3.48%** |

### Crucial Empirical Takeaway on Multi-Horizon Decay
1. **Days 1–5**: The direct Ridge regression model demonstrates clear superiority, reducing Day-1 MAE by nearly 30% and Day-2 MAE by 20%.
2. **Day 6**: Direct Ridge regression and Seasonal-Naive converge to parity (~179 vs 181 MU).
3. **Day 7**: At 7 days ahead, the simple Seasonal-Naive baseline ($y_{t-7}$) achieves **181.14 MU**, slightly outperforming the direct statistical model (**186.73 MU**). Because short-term autocorrelation has fully decayed, trying to estimate linear combinations across 7-day-old lags introduces higher variance than simply adhering to the weekly calendar anchor.
4. **Architectural Recommendation for Phase 3 API**: For $H \in \{1 \dots 5\}$, serve the certified Ridge Direct Model; for $H=7$, provide the Seasonal-Naive anchor alongside the direct model as the calibrated upper bound.

---

## 6. Software Architecture, Runtime, & Test Verification

### Zero External Dependencies
Because the secure execution sandbox blocks external internet access (`pip install` prohibited), the entire engine was engineered using only the **Python 3.12 Standard Library** (`math`, `sqlite3`, `datetime`, `json`).
- Gaussian elimination linear solver with partial pivoting for closed-form Ridge Normal Equations: $(X^T X + \alpha I) w = X^T y$.
- Complete model fit and evaluation takes **< 1.0 second**.

### Production Artifacts Created
- `scripts/train_forecast_model.py`: Full training, validation, holdout, and multi-horizon direct modeling pipeline.
- `models/certified_energy_model.json`: Serialized certified model for `energy_met_mu` containing weights, scalers, and all 7 direct horizon estimators.
- `models/certified_peak_model.json`: Serialized certified model for `peak_met_mw`.
- `data/clean/forecast_evaluation_results.json`: Full machine-readable metrics database.
- `tests/test_forecasting.py`: 8 comprehensive unit tests.

### Test Execution Summary
All **23 unit tests** in the test suite pass with 100% success in **0.865 seconds**:
```
python -m unittest discover tests
.......................
----------------------------------------------------------------------
Ran 23 tests in 0.865s

OK
```
- 15 Data Integrity & API Tests (`test_data_invariants.py`, `test_server_endpoints.py`)
- 8 Forecasting Tests (`test_forecasting.py`):
  1. `test_calendar_lag_correctness`: Verifies gap handling (excludes dates following missing 2023-03-30).
  2. `test_chronological_splitting_integrity`: Verifies zero overlap and strict chronological ordering.
  3. `test_leakage_prevention_in_feature_scaling`: Verifies scaler parameters are fit only on training set.
  4. `test_metric_calculations_and_edge_cases`: Verifies MAE, RMSE, and non-zero MAPE denominator protection.
  5. `test_model_serialization_and_reproducibility`: Verifies models reload from JSON with identical numerical predictions.
  6. `test_fallback_gatekeeper_selection`: Verifies automatic reversion to baseline if ML fails validation.
  7. `test_baseline_reproduction_accuracy`: Verifies Method A (~89.92 MU) and strict calendar benchmarks.
  8. `test_saved_artifacts_validity`: Verifies presence and structure of `models/*.json` and evaluation JSON.

---

## 7. Limitations & Transition to Phase 3

1. **Weather Variable Absence**: Real-time UTCI temperature data ends in 2022. Future improvements can ingest weather forecasts from IMD / Open-Meteo once live APIs are connected.
2. **Extreme Heatwave Variance**: In May–June, MAPE reaches 1.97% vs 1.06% in winter. Non-linear temperature sensitivity curves could be explored in future iterations.
3. **Phase 3 Readiness**: The model artifacts in `models/` are frozen, verified, and ready to be integrated into `server.py` and the UI dashboard in Phase 3 upon approval.
