# Phase 2: Forecasting Engine & Model Evaluation Report
**EnergySense / GridSense Platform**  
*Evaluation Date: October 2026 | Dataset Range: 2013-01-01 to 2024-04-28*  
*Protocol Audit Reference: [docs/forecast_protocol_audit.md](file:///c:/Users/heman/Desktop/project_working/energySense/docs/forecast_protocol_audit.md)*

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

## 2. Leakage-Safe Feature Engineering & Holdout Accounting

To guarantee zero data leakage across chronological splits:
- **Exact Calendar Lags**: For forecast origin day $D$, candidate historical lags are derived strictly via datetime arithmetic: $D, D-1, D+h-7, D+h-14, D+h-21, D+h-28$.
- **No Artificial Imputation**: Missing dates in history are never forward-filled or interpolated for model training. If a required exact lag is absent, the observation is omitted from the sample matrix.
- **Robust Rolling Windows**: Rolling 7-day and 28-day historical averages at origin $D$ require $\ge 5$ and $\ge 20$ valid observations respectively, strictly bounded by $D$.
- **Calendar & Seasonality Features**: Day-of-week one-hot encoding (Mon–Sat, Sun reference), 1st and 2nd harmonic Fourier terms ($\sin/\cos$ on day-of-year), and normalized secular trend.
- **Strictly Out-of-Sample Scaler**: `StandardFeatureScaler` fits means and standard deviations exclusively on training data ($2013-2021$). Validation and holdout data use the frozen training parameters.
- **Holdout Date Accounting**:
  - Total holdout calendar range: 484 days (2023-01-01 to 2024-04-28).
  - Database records: 483 rows (1 missing date in canonical data: `2023-03-30`).
  - Evaluated Day-Ahead ($H=1$) dates: **477 dates**.
  - Omitted dates ($N=6$): `2023-03-31`, `2023-04-01`, `2023-04-06`, `2023-04-13`, `2023-04-20`, `2023-04-27`. Each is excluded because an exact required historical lag fell onto missing date `2023-03-30`.

---

## 3. Validation Performance & Model Selection (2022)

The 2022 validation year ($N=338$ complete feature dates) served as the decision gatekeeper.

### Validation Results (Day-1 Ahead, $H=1$)
| Target | Candidate Model | Config / Hyperparameters | Val MAE | Val RMSE | Val MAPE (%) | Improvement vs Persistence | Selection Decision |
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

---

## 5. Origin-Aligned Seven-Day Forecasting ($D+1 \dots D+7$)

Evaluated on the exact same **442 common holdout forecast origins** ($2023-01-01$ to $2024-04-21$) where all origin features and all 7 future actual targets exist:

### National Daily Energy Met (`energy_met_mu`, MU)
| Horizon | Target Date | Origin Persistence ($y_D$) | Origin Seasonal-Naive ($y_{D+h-7}$) | Direct Ridge ($M_h$) | Ridge RMSE | Ridge MAPE (%) | vs Persistence | vs Seasonal-Naive |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Day 1** | $D+1$ | 89.36 MU | 176.91 MU | **63.36 MU** | 84.87 MU | 1.45% | **+29.10%** | **+64.19%** |
| **Day 2** | $D+2$ | 132.95 MU | 176.56 MU | **105.59 MU** | 137.98 MU | 2.42% | **+20.57%** | **+40.19%** |
| **Day 3** | $D+3$ | 155.87 MU | 176.64 MU | **129.71 MU** | 168.04 MU | 2.98% | **+16.78%** | **+26.57%** |
| **Day 4** | $D+4$ | 168.89 MU | 177.08 MU | **148.84 MU** | 189.70 MU | 3.41% | **+11.87%** | **+15.94%** |
| **Day 5** | $D+5$ | 177.24 MU | 176.71 MU | **163.83 MU** | 204.65 MU | 3.74% | **+7.57%** | **+7.29%** |
| **Day 6** | $D+6$ | 176.31 MU | 176.49 MU | **175.22 MU** | 215.48 MU | 3.98% | **+0.62%** | **+0.72%** |
| **Day 7** | $D+7$ | 176.27 MU | **176.27 MU** | 182.25 MU | 223.70 MU | 4.13% | -3.39% | **-3.39%** |

### National Daily Peak Met (`peak_met_mw`, MW)
| Horizon | Target Date | Origin Persistence ($y_D$) | Origin Seasonal-Naive ($y_{D+h-7}$) | Direct Ridge ($M_h$) | Ridge RMSE | Ridge MAPE (%) | vs Persistence | vs Seasonal-Naive |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Day 1** | $D+1$ | 4,744.36 MW | 8,344.84 MW | **3,362.19 MW** | 4,710.25 MW | 1.57% | **+29.13%** | **+59.71%** |
| **Day 2** | $D+2$ | 6,369.34 MW | 8,331.18 MW | **5,070.81 MW** | 6,750.32 MW | 2.37% | **+20.39%** | **+39.13%** |
| **Day 3** | $D+3$ | 7,346.02 MW | 8,322.21 MW | **6,177.84 MW** | 8,018.52 MW | 2.89% | **+15.90%** | **+25.77%** |
| **Day 4** | $D+4$ | 8,030.73 MW | 8,336.44 MW | **7,021.92 MW** | 9,039.55 MW | 3.27% | **+12.56%** | **+15.77%** |
| **Day 5** | $D+5$ | 8,480.94 MW | 8,292.32 MW | **7,666.16 MW** | 9,726.04 MW | 3.56% | **+9.61%** | **+7.55%** |
| **Day 6** | $D+6$ | 8,705.43 MW | 8,278.29 MW | **8,205.28 MW** | 10,240.18 MW | 3.79% | **+5.75%** | **+0.88%** |
| **Day 7** | $D+7$ | 8,252.00 MW | **8,252.00 MW** | 8,524.86 MW | 10,610.12 MW | 3.93% | -3.31% | **-3.31%** |

### Architectural Serving Guidance for Phase 3
1. **Days 1–5**: The direct Ridge regression model demonstrates clear superiority, reducing Day-1 MAE by nearly 30% and Day-2 MAE by 20%.
2. **Day 6**: Direct Ridge regression and Seasonal-Naive converge to statistical parity.
3. **Day 7**: The simple Seasonal-Naive baseline ($y_{D+7-7} = y_D$, MAE = 176.27 MU) edges out the linear model (MAE = 182.25 MU).
4. **Phase 3 Recommendation**: For $H \in \{1 \dots 5\}$, serve the certified Ridge Direct Model; for $H=7$, serve the Seasonal-Naive anchor alongside the direct model as the calibrated reference.

---

## 6. Software Architecture, Runtime, & Test Verification

- Zero external dependencies: Built strictly with Python 3.12 Standard Library.
- Complete pipeline fit and evaluation executes in **< 1.0s**.
- Model artifacts `models/certified_energy_model.json` and `models/certified_peak_model.json` can be loaded and executed independently without retraining.
- All 24 unit tests pass in **0.57s**:
```
python -m unittest discover tests
........................
----------------------------------------------------------------------
Ran 24 tests in 0.569s

OK
```
