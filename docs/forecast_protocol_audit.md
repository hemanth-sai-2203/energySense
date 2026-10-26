# Forecasting Protocol & Artifact Verification Audit
**EnergySense / GridSense Platform**  
*Audit Date: October 2026 | Dataset Range: 2013-01-01 to 2024-04-28*

---

## 1. Audit of the Seven-Day Forecast Protocol

### Distinction Between Forecasting Setups
A critical distinction in time-series forecasting is between a rolling one-day-ahead forecast and a multi-day forecast issued from a single fixed forecast origin:

1. **Protocol 1: Rolling One-Day-Ahead Forecast ($H=1$)**
   - **Issuing Time**: Evaluated on successive target calendar dates $t \in [2023-01-01, 2024-04-28]$.
   - **Forecast Origin**: For target day $t$, the forecast origin is strictly $D = t - 1$.
   - **Information Set**: Only observations and calendar statistics up to $t-1$ are used.
   - **Target**: Next-day national power ($y_t$).
   - **Baselines**:
     - Day-1 Persistence: $\hat{y}_t^{\text{persist}} = y_{t-1}$
     - Seasonal-Naive: $\hat{y}_t^{\text{snaive}} = y_{t-7}$

2. **Protocol 2: Origin-Aligned Seven-Day Forecast ($D+1 \dots D+7$)**
   - **Issuing Time**: A single forecast is issued at origin date $D$ (e.g. at 23:59 on date $D$ or morning of $D+1$).
   - **Target Horizon**: Generates the complete 7-day future trajectory: $\{ \hat{y}_{D+1}, \hat{y}_{D+2}, \dots, \hat{y}_{D+7} \}$.
   - **Information Boundary**: **Every prediction for all 7 horizons must use ONLY information available on or before origin date $D$.** No actual observations from $D+1$ onward enter any feature or prediction.
   - **Direct Model Formulation**: For each horizon $h \in \{1 \dots 7\}$, a dedicated direct estimator $M_h(\mathbf{x}_{D, h})$ predicts $y_{D+h}$.
     - Feature vector $\mathbf{x}_{D, h}$ available at origin $D$:
       - Latest observed actual: $y_D$
       - Day prior to origin: $y_{D-1}$
       - Target-aligned weekly seasonal lag: $y_{D+h-7}$ (Note: since $1 \le h \le 7$, $D+h-7 \le D$. It is strictly known at origin $D$!)
       - Preceding weekly lags: $y_{D+h-14}, y_{D+h-21}, y_{D+h-28}$
       - Historical rolling statistics at origin $D$: 7-day mean of $[D-6 \dots D]$, 28-day mean of $[D-27 \dots D]$
       - Target date $D+h$ calendar features: Day of week, Fourier annual seasonality ($\sin/\cos$ on day-of-year), normalized trend.
   - **Origin-Aligned Baselines**:
     - **Origin Persistence**: At origin $D$, the last known actual is $y_D$. Therefore, the persistence prediction for all future days is $\hat{y}_{D+h}^{\text{persist}} = y_D$.
     - **Origin Seasonal-Naive**: For target day $D+h$, the same day-of-week 7 days prior to target is $(D+h-7) \le D$. Therefore, $\hat{y}_{D+h}^{\text{snaive}} = y_{D+h-7}$.
     *(Note: for $h=7$, $D+7-7 = D$, so Seasonal-Naive and Persistence are mathematically identical to $y_D$.)*

### Empirical Comparison on Common Holdout Origins ($N=442$)
All models were evaluated on the **exact same 442 common holdout origins** ($2023-01-01$ to $2024-04-21$) where all origin features and all 7 future target actuals exist:

#### Primary Target: National Daily Energy Met (`energy_met_mu`, MU)
| Horizon | Target Date | Origin Persistence ($y_D$) | Origin Seasonal-Naive ($y_{D+h-7}$) | Direct Ridge ($M_h$) | Ridge RMSE | Ridge MAPE (%) | vs Persistence | vs Seasonal-Naive | Empirical Status |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **Day 1** | $D+1$ | 89.36 MU (2.07%) | 176.91 MU (4.10%) | **63.36 MU** | 84.87 MU | 1.45% | **+29.10%** | **+64.19%** | Ridge Superior |
| **Day 2** | $D+2$ | 132.95 MU (3.08%) | 176.56 MU (4.09%) | **105.59 MU** | 137.98 MU | 2.42% | **+20.57%** | **+40.19%** | Ridge Superior |
| **Day 3** | $D+3$ | 155.87 MU (3.61%) | 176.64 MU (4.09%) | **129.71 MU** | 168.04 MU | 2.98% | **+16.78%** | **+26.57%** | Ridge Superior |
| **Day 4** | $D+4$ | 168.89 MU (3.91%) | 177.08 MU (4.10%) | **148.84 MU** | 189.70 MU | 3.41% | **+11.87%** | **+15.94%** | Ridge Superior |
| **Day 5** | $D+5$ | 177.24 MU (4.10%) | 176.71 MU (4.09%) | **163.83 MU** | 204.65 MU | 3.74% | **+7.57%** | **+7.29%** | Ridge Superior |
| **Day 6** | $D+6$ | 176.31 MU (4.07%) | 176.49 MU (4.08%) | **175.22 MU** | 215.48 MU | 3.98% | **+0.62%** | **+0.72%** | Parity |
| **Day 7** | $D+7$ | 176.27 MU (4.07%) | **176.27 MU** (4.07%) | 182.25 MU | 223.70 MU | 4.13% | -3.39% | **-3.39%** | Seasonal-Naive Preferred |

#### Secondary Target: National Daily Peak Met (`peak_met_mw`, MW)
| Horizon | Target Date | Origin Persistence ($y_D$) | Origin Seasonal-Naive ($y_{D+h-7}$) | Direct Ridge ($M_h$) | Ridge RMSE | Ridge MAPE (%) | vs Persistence | vs Seasonal-Naive | Empirical Status |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **Day 1** | $D+1$ | 4,744.36 MW (2.22%) | 8,344.84 MW (3.93%) | **3,362.19 MW** | 4,710.25 MW | 1.57% | **+29.13%** | **+59.71%** | Ridge Superior |
| **Day 2** | $D+2$ | 6,369.34 MW (2.99%) | 8,331.18 MW (3.92%) | **5,070.81 MW** | 6,750.32 MW | 2.37% | **+20.39%** | **+39.13%** | Ridge Superior |
| **Day 3** | $D+3$ | 7,346.02 MW (3.46%) | 8,322.21 MW (3.92%) | **6,177.84 MW** | 8,018.52 MW | 2.89% | **+15.90%** | **+25.77%** | Ridge Superior |
| **Day 4** | $D+4$ | 8,030.73 MW (3.78%) | 8,336.44 MW (3.93%) | **7,021.92 MW** | 9,039.55 MW | 3.27% | **+12.56%** | **+15.77%** | Ridge Superior |
| **Day 5** | $D+5$ | 8,480.94 MW (3.98%) | 8,292.32 MW (3.90%) | **7,666.16 MW** | 9,726.04 MW | 3.56% | **+9.61%** | **+7.55%** | Ridge Superior |
| **Day 6** | $D+6$ | 8,705.43 MW (4.08%) | 8,278.29 MW (3.89%) | **8,205.28 MW** | 10,240.18 MW | 3.79% | **+5.75%** | **+0.88%** | Parity |
| **Day 7** | $D+7$ | 8,252.00 MW (3.87%) | **8,252.00 MW** (3.87%) | 8,524.86 MW | 10,610.12 MW | 3.93% | -3.31% | **-3.31%** | Seasonal-Naive Preferred |

---

## 2. Audit of Holdout Comparability & Date Accounting

### Why Holdout Has 483 Calendar Observations but 477 Evaluated $H=1$ Dates
- **Holdout Calendar Range**: 2023-01-01 to 2024-04-28 (484 possible calendar dates).
- **Recorded Database Rows**: 483 rows (exactly 1 missing date in canonical data: `2023-03-30`).
- **Evaluated Day-Ahead ($H=1$) Dates**: **477 dates**.
- **Omitted Dates ($N=6$) and Root Causes**:
  Because our pipeline strictly rejects artificial forward-filling or imputation of missing target values, any target date whose exact historical calendar lags fall onto `2023-03-30` is safely omitted from model evaluation:

| Excluded Date | Day of Week | Missing Historical Lag Required | Offset from Missing Date | Reason for Exclusion |
| :---: | :---: | :---: | :---: | :--- |
| **2023-03-31** | Friday | $t - 1$ (`2023-03-30`) | +1 day | Origin $D = t-1$ does not exist in SQLite database. |
| **2023-04-01** | Saturday | $t - 2$ (`2023-03-30`) | +2 days | Lag $D-1$ (`2023-03-30`) absent from origin feature vector. |
| **2023-04-06** | Thursday | $t - 7$ (`2023-03-30`) | +7 days | Same-day-of-week lag $t-7$ absent. |
| **2023-04-13** | Thursday | $t - 14$ (`2023-03-30`) | +14 days | Weekly seasonal lag $t-14$ absent. |
| **2023-04-20** | Thursday | $t - 21$ (`2023-03-30`) | +21 days | Weekly seasonal lag $t-21$ absent. |
| **2023-04-27** | Thursday | $t - 28$ (`2023-03-30`) | +28 days | Weekly seasonal lag $t-28$ absent. |

$$483 \text{ database rows} - 6 \text{ missing-lag dates} = \mathbf{477 \text{ strictly evaluated dates}}.$$

### Why Multi-Horizon Evaluation Uses 442 Common Origins
For an origin date $D$ to evaluate a complete 7-day trajectory ($D+1 \dots D+7$):
1. **Target Range Boundary**: Since the holdout dataset ends on `2024-04-28`, any forecast origin $D > 2024-04-21$ would require targets beyond the dataset boundary ($D+7 > 2024-04-28$). This bounds the maximum origin to `2024-04-21`.
2. **Intermediate Missing Targets**: Target trajectories passing over `2023-03-30` (origins `2023-03-23` to `2023-03-29`) lack actual observations for ground-truth comparison.
3. **Origins with Missing History**: Origins around `2023-03-30` lack required historical features.
4. Total calendar origins between `2023-01-01` and `2024-04-21` is 477. Removing the missing-history and missing-target windows leaves **exactly 442 complete, common forecast origins**. Every candidate model and baseline is evaluated on the exact same 442 origins.

---

## 3. Training & Evaluation Integrity Verification

| Audit Checkpoint | Verification Status | Evidence / Implementation Details |
| :--- | :---: | :--- |
| **Leakage Prevention** | **VERIFIED** | Feature extraction for origin $D$ uses only $d \le D$. Scalers fit strictly on $2013-2021$ training set. Validation and holdout data use frozen $(\mu, \sigma)$. |
| **Chronological Boundaries** | **VERIFIED** | Zero data overlap between Train ($\le 2021$), Val ($2022$), and Holdout ($\ge 2023$). No shuffling or future lookahead. |
| **Model Selection Protocol** | **VERIFIED** | Ridge hyperparameter ($\alpha=0.01$) selected strictly on 2022 validation. Holdout was evaluated only after decisions were frozen. |
| **Artifact Reproducibility** | **VERIFIED** | `models/certified_energy_model.json` and `models/certified_peak_model.json` reload in pure Python and match training code predictions with 0.0000 discrepancy. |
| **Unit Test Verification** | **VERIFIED** | 24 automated unit tests pass in **0.57s** (`test_forecasting.py`, `test_data_invariants.py`, `test_server_endpoints.py`). |

---

## 4. Serving Contract for Future `/api/forecast` Endpoint

When Phase 3 is approved, the `/api/forecast` endpoint will be implemented on the existing Python server with the following certified contract:

### Request Specification
- **Method**: `GET`
- **Path**: `/api/forecast`
- **Query Parameters**:
  - `target` *(optional string)*: `"energy_met_mu"` (default) or `"peak_met_mw"`.
  - `origin` *(optional string, format `YYYY-MM-DD`)*: Forecast origin date. Defaults to the latest available date in SQLite (`2024-04-28`).
  - `horizon` *(optional integer `1..7`)*: Forecast horizon. Defaults to `7` (returns complete 7-day trajectory).

### Success Response Schema (HTTP 200)
```json
{
  "status": "success",
  "forecast_origin": "2024-04-28",
  "target": "energy_met_mu",
  "target_label": "National Daily Energy Met",
  "units": "MU",
  "model_id": "ridge_direct_v1",
  "validation_status": "certified_beaten_persistence",
  "validation_mae": 54.56,
  "validation_improvement_pct": 34.7,
  "active_model": "RidgeRegressor",
  "predictions": [
    {
      "horizon": 1,
      "target_date": "2024-04-29",
      "predicted_value": 4721.45,
      "recommended_model": "ridge",
      "ridge_prediction": 4721.45,
      "persistence_baseline": 4680.12,
      "seasonal_naive_baseline": 4610.30,
      "baseline_status": "ridge_superior"
    },
    {
      "horizon": 7,
      "target_date": "2024-05-05",
      "predicted_value": 4680.12,
      "recommended_model": "seasonal_naive",
      "ridge_prediction": 4710.22,
      "persistence_baseline": 4680.12,
      "seasonal_naive_baseline": 4680.12,
      "baseline_status": "seasonal_anchor_preferred"
    }
  ],
  "data_quality": {
    "origin_available": true,
    "required_lags_present": 6,
    "missing_lags": [],
    "rolling_window_sample_count": 28
  }
}
```

### Error & Edge-Case Handling Policy
1. **Unavailable Historical Lags** (HTTP 422 Unprocessable Entity):
   - Trigger: Origin date $D$ lacks required lags (e.g., $D-1$ or $D-7$ fell on an unobserved historical gap).
   - Response:
     ```json
     {
       "status": "error",
       "code": "UNAVAILABLE_LAG",
       "message": "Cannot compute ML forecast from origin 2023-03-31: required lag 2023-03-30 is absent from canonical database.",
       "fallback_available": true,
       "fallback_recommendation": "Use latest available valid origin 2023-03-29."
     }
     ```
2. **Corrupted or Missing Model Artifact** (HTTP 503 / Degraded Fallback):
   - Trigger: `models/certified_energy_model.json` missing or invalid JSON.
   - Response: Automatically fallback to zero-dependency Day-0 Persistence and Seasonal-Naive baseline with `"status": "degraded"`, `"active_model": "PersistenceBaseline"`, and `"message": "Certified model artifact unavailable; fell back to Persistence."`
3. **Future Origin Date Requested** (HTTP 400 Bad Request):
   - Trigger: Requested origin $D > \text{max\_db\_date}$ (e.g. $D = 2026-10-26$).
   - Response: `{"status": "error", "code": "FUTURE_ORIGIN_NOT_OBSERVED", "message": "Forecast origin 2026-10-26 exceeds latest database observation 2024-04-28. Forecasts must originate from an observed historical date."}`
4. **Legitimate Future Horizon Request**:
   - When origin $D = \text{latest\_db\_date}$ (`2024-04-28`), predictions for $D+1 \dots D+7$ (`2024-04-29` to `2024-05-05`) are legitimately computed and served as forward-looking projections into the unobserved future.

---

## 5. Audit Conclusion & Readiness Status

1. **Protocol Rigor**: Both rolling day-ahead and origin-aligned 7-day multi-horizon forecasting have been audited and mathematically separated.
2. **Fair Comparisons**: All models are compared on identical dates without artificial imputation.
3. **Artifact Integrity**: Certified model artifacts in `models/` load independently and reproduce all reported metrics in pure Python standard library.
4. **Readiness**: The model pipeline is **100% ready for Phase 3 API and UI integration**.
