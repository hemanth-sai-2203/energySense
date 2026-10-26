"""
Phase 2: Forecasting Engine & Model Training Pipeline
EnergySense / GridSense Platform

This script implements a reproducible, zero-external-dependency forecasting engine:
1. Baselines: Day-1 Persistence and Seasonal-Naive (t-7).
2. Features: Leakage-safe calendar features, exact calendar lags (t-1, t-2, t-7, t-14, t-21, t-28),
   and rolling statistics calculated strictly from observations prior to forecast time.
3. Models: Closed-form L2 Ridge Regression (pure Python Gaussian elimination solver)
   and Compact Regression Tree (variance reduction).
4. Targets: National Daily Energy Met (MU) [Primary] and Peak Met (MW) [Secondary].
5. Evaluation:
   - Train: 2013-2021
   - Validation: 2022 (Model & hyperparameter selection, COVID structural break test)
   - Holdout: 2023-01-01 to 2024-04-28 (Frozen evaluation)
   - Multi-horizon: 1-day ahead (H=1) and 7-day ahead (H=1..7 direct multi-step).
   - Model fallback gatekeeper: selects baseline if ML fails to beat baseline on validation.
6. Artifacts:
   - models/certified_energy_model.json
   - models/certified_peak_model.json
   - data/clean/forecast_evaluation_results.json
"""

import os
import sys
import math
import json
import sqlite3
import datetime
from typing import Dict, List, Tuple, Any, Optional

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "clean", "energysense.db")
MODELS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models")
RESULTS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "clean", "forecast_evaluation_results.json")


# ============================================================================
# 1. PURE PYTHON LINEAR ALGEBRA & RIDGE REGRESSION
# ============================================================================

def matrix_transpose(A: List[List[float]]) -> List[List[float]]:
    if not A or not A[0]:
        return []
    n_rows, n_cols = len(A), len(A[0])
    return [[A[i][j] for i in range(n_rows)] for j in range(n_cols)]

def matrix_multiply(A: List[List[float]], B: List[List[float]]) -> List[List[float]]:
    n_rows_A, n_cols_A = len(A), len(A[0])
    n_rows_B, n_cols_B = len(B), len(B[0])
    assert n_cols_A == n_rows_B, f"Shape mismatch: {n_cols_A} vs {n_rows_B}"
    
    # Transpose B for cache-friendly row dot products
    BT = matrix_transpose(B)
    return [[sum(A[i][k] * BT[j][k] for k in range(n_cols_A)) for j in range(n_cols_B)] for i in range(n_rows_A)]

def matrix_vector_multiply(A: List[List[float]], v: List[float]) -> List[float]:
    n_cols = len(v)
    return [sum(row[k] * v[k] for k in range(n_cols)) for row in A]

def solve_linear_system(A: List[List[float]], b: List[float]) -> List[float]:
    """Gaussian elimination with partial pivoting."""
    n = len(A)
    # Augmented matrix
    M = [A[i][:] + [b[i]] for i in range(n)]
    
    for i in range(n):
        # Find pivot
        max_val = abs(M[i][i])
        max_row = i
        for r in range(i + 1, n):
            if abs(M[r][i]) > max_val:
                max_val = abs(M[r][i])
                max_row = r
        if max_val < 1e-12:
            raise ValueError(f"Matrix is singular or near-singular at index {i}")
        if max_row != i:
            M[i], M[max_row] = M[max_row], M[i]
            
        pivot = M[i][i]
        for col in range(i, n + 1):
            M[i][col] /= pivot
            
        for r in range(n):
            if r != i and abs(M[r][i]) > 1e-14:
                factor = M[r][i]
                for col in range(i, n + 1):
                    M[r][col] -= factor * M[i][col]
                    
    return [M[i][n] for i in range(n)]

class StandardFeatureScaler:
    """Standardize features strictly using training set statistics."""
    def __init__(self):
        self.means: List[float] = []
        self.stds: List[float] = []

    def fit(self, X: List[List[float]]):
        n_samples = len(X)
        n_features = len(X[0])
        self.means = [0.0] * n_features
        self.stds = [1.0] * n_features

        for j in range(n_features):
            vals = [X[i][j] for i in range(n_samples)]
            mean = sum(vals) / n_samples
            var = sum((v - mean) ** 2 for v in vals) / (n_samples - 1 if n_samples > 1 else 1)
            std = math.sqrt(var)
            self.means[j] = mean
            self.stds[j] = std if std > 1e-8 else 1.0

    def transform(self, X: List[List[float]]) -> List[List[float]]:
        return [[(row[j] - self.means[j]) / self.stds[j] for j in range(len(row))] for row in X]

    def to_dict(self) -> Dict[str, Any]:
        return {"means": self.means, "stds": self.stds}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]):
        scaler = cls()
        scaler.means = data["means"]
        scaler.stds = data["stds"]
        return scaler

class PureRidgeRegressor:
    """Exact L2 Regularized Ridge Regressor solved via normal equations."""
    def __init__(self, alpha: float = 1.0):
        self.alpha = alpha
        self.weights: List[float] = []
        self.intercept: float = 0.0
        self.scaler = StandardFeatureScaler()

    def fit(self, X: List[List[float]], y: List[float]):
        n_samples = len(X)
        n_features = len(X[0])
        
        # Center target
        self.intercept = sum(y) / n_samples
        y_centered = [yi - self.intercept for yi in y]
        
        # Scale features
        self.scaler.fit(X)
        X_scaled = self.scaler.transform(X)
        
        # XT * X + alpha * I
        XT = matrix_transpose(X_scaled)
        XT_X = matrix_multiply(XT, X_scaled)
        for i in range(n_features):
            XT_X[i][i] += self.alpha
            
        XT_y = matrix_vector_multiply(XT, y_centered)
        self.weights = solve_linear_system(XT_X, XT_y)

    def predict(self, X: List[List[float]]) -> List[float]:
        X_scaled = self.scaler.transform(X)
        preds = []
        for row in X_scaled:
            dot = sum(w * val for w, val in zip(self.weights, row))
            preds.append(self.intercept + dot)
        return preds

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_type": "RidgeRegressor",
            "alpha": self.alpha,
            "intercept": self.intercept,
            "weights": self.weights,
            "scaler": self.scaler.to_dict()
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]):
        model = cls(alpha=data["alpha"])
        model.intercept = data["intercept"]
        model.weights = data["weights"]
        model.scaler = StandardFeatureScaler.from_dict(data["scaler"])
        return model


# ============================================================================
# 2. PURE PYTHON COMPACT REGRESSION TREE
# ============================================================================

class TreeNode:
    def __init__(self, is_leaf: bool = False, value: float = 0.0,
                 feature_idx: int = -1, threshold: float = 0.0,
                 left: Optional['TreeNode'] = None, right: Optional['TreeNode'] = None):
        self.is_leaf = is_leaf
        self.value = value
        self.feature_idx = feature_idx
        self.threshold = threshold
        self.left = left
        self.right = right

    def to_dict(self) -> Dict[str, Any]:
        if self.is_leaf:
            return {"is_leaf": True, "value": self.value}
        return {
            "is_leaf": False,
            "feature_idx": self.feature_idx,
            "threshold": self.threshold,
            "left": self.left.to_dict() if self.left else None,
            "right": self.right.to_dict() if self.right else None
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'TreeNode':
        if d["is_leaf"]:
            return cls(is_leaf=True, value=d["value"])
        node = cls(
            is_leaf=False,
            feature_idx=d["feature_idx"],
            threshold=d["threshold"],
            left=cls.from_dict(d["left"]) if d["left"] else None,
            right=cls.from_dict(d["right"]) if d["right"] else None
        )
        return node

class PureDecisionTreeRegressor:
    """Compact greedy variance-reduction regression tree."""
    def __init__(self, max_depth: int = 5, min_samples_split: int = 20):
        self.max_depth = max_depth
        self.min_samples_split = min_samples_split
        self.root: Optional[TreeNode] = None

    def fit(self, X: List[List[float]], y: List[float]):
        self.root = self._build_tree(X, y, depth=0)

    def _build_tree(self, X: List[List[float]], y: List[float], depth: int) -> TreeNode:
        n_samples = len(y)
        mean_y = sum(y) / n_samples
        
        if depth >= self.max_depth or n_samples < self.min_samples_split:
            return TreeNode(is_leaf=True, value=mean_y)

        # Baseline variance
        total_var = sum((val - mean_y) ** 2 for val in y)
        if total_var < 1e-7:
            return TreeNode(is_leaf=True, value=mean_y)

        best_gain = 0.0
        best_feat = -1
        best_thresh = 0.0
        n_features = len(X[0])

        for j in range(n_features):
            feat_vals = sorted(list(set(X[i][j] for i in range(n_samples))))
            if len(feat_vals) < 2:
                continue
            if len(feat_vals) > 15:
                step = len(feat_vals) // 15
                candidates = [feat_vals[k] for k in range(0, len(feat_vals), step)]
            else:
                candidates = feat_vals

            for thresh in candidates:
                left_y = [y[i] for i in range(n_samples) if X[i][j] <= thresh]
                right_y = [y[i] for i in range(n_samples) if X[i][j] > thresh]
                if not left_y or not right_y:
                    continue
                mean_l = sum(left_y) / len(left_y)
                mean_r = sum(right_y) / len(right_y)
                var_l = sum((val - mean_l) ** 2 for val in left_y)
                var_r = sum((val - mean_r) ** 2 for val in right_y)
                gain = total_var - (var_l + var_r)
                if gain > best_gain:
                    best_gain = gain
                    best_feat = j
                    best_thresh = thresh

        if best_gain <= 1e-5 or best_feat == -1:
            return TreeNode(is_leaf=True, value=mean_y)

        left_X = [X[i] for i in range(n_samples) if X[i][best_feat] <= best_thresh]
        left_y = [y[i] for i in range(n_samples) if X[i][best_feat] <= best_thresh]
        right_X = [X[i] for i in range(n_samples) if X[i][best_feat] > best_thresh]
        right_y = [y[i] for i in range(n_samples) if X[i][best_feat] > best_thresh]

        left_node = self._build_tree(left_X, left_y, depth + 1)
        right_node = self._build_tree(right_X, right_y, depth + 1)
        return TreeNode(is_leaf=False, feature_idx=best_feat, threshold=best_thresh,
                        left=left_node, right=right_node)

    def _predict_row(self, row: List[float], node: TreeNode) -> float:
        if node.is_leaf:
            return node.value
        if row[node.feature_idx] <= node.threshold:
            return self._predict_row(row, node.left)
        else:
            return self._predict_row(row, node.right)

    def predict(self, X: List[List[float]]) -> List[float]:
        return [self._predict_row(row, self.root) for row in X]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_type": "DecisionTreeRegressor",
            "max_depth": self.max_depth,
            "min_samples_split": self.min_samples_split,
            "root": self.root.to_dict() if self.root else None
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'PureDecisionTreeRegressor':
        tree = cls(max_depth=d["max_depth"], min_samples_split=d["min_samples_split"])
        tree.root = TreeNode.from_dict(d["root"]) if d["root"] else None
        return tree


# ============================================================================
# 3. METRICS EVALUATION
# ============================================================================

def calculate_metrics(y_true: List[float], y_pred: List[float]) -> Dict[str, float]:
    """Calculate MAE, RMSE, and MAPE with non-zero denominator protection."""
    n = len(y_true)
    if n == 0:
        return {"mae": 0.0, "rmse": 0.0, "mape": 0.0, "count": 0}
    mae = sum(abs(yt - yp) for yt, yp in zip(y_true, y_pred)) / n
    rmse = math.sqrt(sum((yt - yp) ** 2 for yt, yp in zip(y_true, y_pred)) / n)
    mape = sum(abs(yt - yp) / abs(yt) for yt, yp in zip(y_true, y_pred) if abs(yt) > 1e-4) / n * 100.0
    return {
        "mae": round(mae, 4),
        "rmse": round(rmse, 4),
        "mape": round(mape, 4),
        "count": n
    }


# ============================================================================
# 4. DATA LOADING & CALENDAR-CORRECT FEATURE ENGINEERING
# ============================================================================

def load_clean_data(db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT date, energy_met_mu, peak_met_mw 
        FROM daily_india_demand 
        ORDER BY date ASC
    """)
    rows = cursor.fetchall()
    conn.close()
    
    records = []
    for r in rows:
        records.append({
            "date": r[0],
            "dt": datetime.date.fromisoformat(r[0]),
            "energy_met_mu": float(r[1]) if r[1] is not None else None,
            "peak_met_mw": float(r[2]) if r[2] is not None else None
        })
    return records

def build_dataset_for_target(
    records: List[Dict[str, Any]],
    target_col: str = "energy_met_mu",
    horizon: int = 1,
    include_covid_feature: bool = False
) -> Tuple[List[str], List[List[float]], List[float], List[str]]:
    """
    Constructs calendar-correct, leakage-safe features for forecasting target_col at forecast horizon h (days ahead).
    
    For horizon h (h >= 1):
      Forecast target is y(t).
      Available information is strictly up to calendar date (t - h).
      Exact calendar lags:
        - Most recent available day: (t - h)
        - Day before that: (t - h - 1)
        - Preceding same-day-of-week: (t - h - 6) for h=1 (i.e. t-7), or (t - 7) if h <= 7
        - Preceding weeks: (t - 14), (t - 21), (t - 28)
      Rolling statistics:
        - 7-day window of available days in [t - h - 6 .. t - h] (requires >= 5 available observations)
        - 28-day window of available days in [t - h - 27 .. t - h] (requires >= 20 available observations)
      Calendar features of target date t:
        - Day of week (0=Mon..6=Sun) one-hot (6 binary features, Sunday as reference)
        - Annual seasonality: Fourier sin/cos 1st and 2nd harmonics
        - Trend: normalized days from 2013-01-01
        - (Optional) is_lockdown_2020: 1 if date in 2020-03-24..2020-05-31 else 0
    """
    date_map = {r["dt"]: r[target_col] for r in records if r[target_col] is not None}
    
    # Exact calendar lags relative to target day t
    # For H=1: lags from t are 1, 2, 7, 14, 21, 28
    # For H=h: latest available is t-h, next is t-h-1; for seasonal weekly anchor: max(h, 7), max(h, 14), etc.
    lag_1 = horizon
    lag_2 = horizon + 1
    lag_7 = max(horizon, 7)
    lag_14 = max(horizon + 7, 14)
    lag_21 = max(horizon + 14, 21)
    lag_28 = max(horizon + 21, 28)
    
    lag_offsets = [lag_1, lag_2, lag_7, lag_14, lag_21, lag_28]
    
    feature_names = [
        f"lag_{lag_1}", f"lag_{lag_2}", f"lag_{lag_7}",
        f"lag_{lag_14}", f"lag_{lag_21}", f"lag_{lag_28}",
        "roll_mean_7", "roll_mean_28",
        "trend_years",
        "sin_doy_1", "cos_doy_1", "sin_doy_2", "cos_doy_2",
        "dow_mon", "dow_tue", "dow_wed", "dow_thu", "dow_fri", "dow_sat"
    ]
    if include_covid_feature:
        feature_names.append("is_lockdown_2020")

    dates_out = []
    X_out = []
    y_out = []

    t0 = datetime.date(2013, 1, 1)

    for r in records:
        dt = r["dt"]
        y_val = r[target_col]
        if y_val is None:
            continue
            
        # Determine lag calendar dates
        lag_dates = [dt - datetime.timedelta(days=k) for k in lag_offsets]
        
        # Verify all exact calendar lags exist without artificial imputation
        if not all(ld in date_map for ld in lag_dates):
            continue
            
        lags = [date_map[ld] for ld in lag_dates]
        
        # 7-day rolling window of available history [t - h - 6 .. t - h]
        roll7_vals = [date_map[dt - datetime.timedelta(days=horizon + k)] 
                      for k in range(7) if (dt - datetime.timedelta(days=horizon + k)) in date_map]
        if len(roll7_vals) < 5:
            continue
        roll_mean_7 = sum(roll7_vals) / float(len(roll7_vals))
        
        # 28-day rolling window of available history [t - h - 27 .. t - h]
        roll28_vals = [date_map[dt - datetime.timedelta(days=horizon + k)] 
                       for k in range(28) if (dt - datetime.timedelta(days=horizon + k)) in date_map]
        if len(roll28_vals) < 20:
            continue
        roll_mean_28 = sum(roll28_vals) / float(len(roll28_vals))

        # Calendar features of forecast target date
        trend_years = (dt - t0).days / 365.25
        doy = dt.timetuple().tm_yday
        sin_doy_1 = math.sin(2.0 * math.pi * doy / 365.25)
        cos_doy_1 = math.cos(2.0 * math.pi * doy / 365.25)
        sin_doy_2 = math.sin(4.0 * math.pi * doy / 365.25)
        cos_doy_2 = math.cos(4.0 * math.pi * doy / 365.25)
        
        dow = dt.weekday() # 0 = Monday, 6 = Sunday
        dow_ohe = [1.0 if dow == k else 0.0 for k in range(6)] # Mon..Sat (Sun is implicit reference)

        row = lags + [roll_mean_7, roll_mean_28, trend_years, sin_doy_1, cos_doy_1, sin_doy_2, cos_doy_2] + dow_ohe
        
        if include_covid_feature:
            is_lockdown = 1.0 if datetime.date(2020, 3, 24) <= dt <= datetime.date(2020, 5, 31) else 0.0
            row.append(is_lockdown)

        dates_out.append(r["date"])
        X_out.append(row)
        y_out.append(y_val)

    return dates_out, X_out, y_out, feature_names


# ============================================================================
# 5. SPLIT & BENCHMARK REPRODUCTION
# ============================================================================

def reproduce_reported_benchmarks(records: List[Dict[str, Any]], target_col: str = "energy_met_mu") -> Dict[str, Any]:
    """
    Investigates and reproduces baseline metrics on 2023-01-01 through 2024-04-28:
    Method A: Row-index shift (i-1), as done in naive exploratory scripts (483 days).
    Method B: Strict calendar lag (t-1 day) on valid calendar dates (482 days).
    Method C: Common valid evaluation set where both t-1 and t-7 exist (481 days).
    """
    holdout_start = datetime.date(2023, 1, 1)
    holdout_end = datetime.date(2024, 4, 28)
    
    date_map = {r["dt"]: r[target_col] for r in records if r[target_col] is not None}
    
    # Method A: Row-index shift
    rec_in_range = [r for r in records if holdout_start <= r["dt"] <= holdout_end and r[target_col] is not None]
    y_true_A = []
    y_pred_persist_A = []
    for r in rec_in_range:
        idx = records.index(r)
        if idx > 0 and records[idx - 1][target_col] is not None:
            y_true_A.append(r[target_col])
            y_pred_persist_A.append(records[idx - 1][target_col])
    metrics_A = calculate_metrics(y_true_A, y_pred_persist_A)

    # Method B: Strict calendar t-1
    y_true_B = []
    y_pred_persist_B = []
    for r in rec_in_range:
        prev_dt = r["dt"] - datetime.timedelta(days=1)
        if prev_dt in date_map:
            y_true_B.append(r[target_col])
            y_pred_persist_B.append(date_map[prev_dt])
    metrics_B = calculate_metrics(y_true_B, y_pred_persist_B)

    # Method C: Common valid set where both t-1 and t-7 exist
    y_true_C = []
    y_pred_persist_C = []
    y_pred_snaive_C = []
    for r in rec_in_range:
        dt_1 = r["dt"] - datetime.timedelta(days=1)
        dt_7 = r["dt"] - datetime.timedelta(days=7)
        if dt_1 in date_map and dt_7 in date_map:
            y_true_C.append(r[target_col])
            y_pred_persist_C.append(date_map[dt_1])
            y_pred_snaive_C.append(date_map[dt_7])
    metrics_C_persist = calculate_metrics(y_true_C, y_pred_persist_C)
    metrics_C_snaive = calculate_metrics(y_true_C, y_pred_snaive_C)

    return {
        "method_A_row_index_shift": {
            "description": "Row index predecessor (includes crossing missing date 2023-03-30 without calendar gap check)",
            "metrics": metrics_A
        },
        "method_B_strict_calendar_lag_1": {
            "description": "Strict calendar t-1 (excludes 2023-03-31 because 2023-03-30 is absent)",
            "metrics": metrics_B
        },
        "method_C_common_valid_evaluation_set": {
            "description": "Common dates where both strict t-1 and t-7 exist (excludes 2023-03-31 and 2023-04-06)",
            "persistence_metrics": metrics_C_persist,
            "seasonal_naive_metrics": metrics_C_snaive
        }
    }


# ============================================================================
# 6. TRAINING & EVALUATION PIPELINE
# ============================================================================

def run_pipeline(records: List[Dict[str, Any]], target_col: str = "energy_met_mu") -> Dict[str, Any]:
    unit_label = "MU" if "energy" in target_col else "MW"
    print(f"\n=======================================================")
    print(f"RUNNING FORECAST PIPELINE FOR TARGET: {target_col.upper()} ({unit_label})")
    print(f"=======================================================")

    # 1. Benchmark Reproduction
    benchmarks = reproduce_reported_benchmarks(records, target_col=target_col)
    if target_col == "energy_met_mu":
        print("\n--- 1. BENCHMARK REPRODUCTION ---")
        print(f"Reported Benchmark in Prior Audit: MAE ~89.92 MU, MAPE ~2.08%")
        print(f"Method A (Row Index, 483 days):     MAE = {benchmarks['method_A_row_index_shift']['metrics']['mae']:.2f} MU, MAPE = {benchmarks['method_A_row_index_shift']['metrics']['mape']:.2f}%")
        print(f"Method B (Strict Cal t-1, 482 days): MAE = {benchmarks['method_B_strict_calendar_lag_1']['metrics']['mae']:.2f} MU, MAPE = {benchmarks['method_B_strict_calendar_lag_1']['metrics']['mape']:.2f}%")
        print(f"Method C (Common Valid, 481 days):   MAE = {benchmarks['method_C_common_valid_evaluation_set']['persistence_metrics']['mae']:.2f} MU, Seasonal Naive = {benchmarks['method_C_common_valid_evaluation_set']['seasonal_naive_metrics']['mae']:.2f} MU")

    # 2. Build Dataset for Day 1 (H=1)
    dates_h1, X_h1, y_h1, feat_names = build_dataset_for_target(records, target_col=target_col, horizon=1, include_covid_feature=False)
    
    # Chronological Split
    # Train: 2013-2021
    # Val: 2022
    # Holdout: 2023 through 2024-04-28
    train_idx = [i for i, d in enumerate(dates_h1) if d <= "2021-12-31"]
    val_idx = [i for i, d in enumerate(dates_h1) if "2022-01-01" <= d <= "2022-12-31"]
    holdout_idx = [i for i, d in enumerate(dates_h1) if d >= "2023-01-01"]

    X_train = [X_h1[i] for i in train_idx]
    y_train = [y_h1[i] for i in train_idx]
    dates_train = [dates_h1[i] for i in train_idx]

    X_val = [X_h1[i] for i in val_idx]
    y_val = [y_h1[i] for i in val_idx]
    dates_val = [dates_h1[i] for i in val_idx]

    X_holdout = [X_h1[i] for i in holdout_idx]
    y_holdout = [y_h1[i] for i in holdout_idx]
    dates_holdout = [dates_h1[i] for i in holdout_idx]

    print(f"\nChronological Split Sample Counts:")
    print(f"  Training (2013-2021):     {len(X_train)} samples ({dates_train[0]} to {dates_train[-1]})")
    print(f"  Validation (2022):        {len(X_val)} samples ({dates_val[0]} to {dates_val[-1]})")
    print(f"  Final Holdout (2023-2024):{len(X_holdout)} samples ({dates_holdout[0]} to {dates_holdout[-1]})")

    # 3. Model Training & Validation Evaluation
    # Persistence baseline on Val (lag_1 is index 0 in feature vector)
    y_pred_val_persist = [row[0] for row in X_val]
    # Seasonal naive (lag_7 is index 2 in feature vector)
    y_pred_val_snaive = [row[2] for row in X_val]

    val_metrics_persist = calculate_metrics(y_val, y_pred_val_persist)
    val_metrics_snaive = calculate_metrics(y_val, y_pred_val_snaive)

    # Train Ridge Models across alpha grid on Train set only
    alphas = [0.01, 0.1, 1.0, 5.0, 10.0, 50.0, 100.0]
    best_ridge_alpha = 1.0
    best_ridge_val_mae = float("inf")
    best_ridge_model = None

    for alpha in alphas:
        ridge = PureRidgeRegressor(alpha=alpha)
        ridge.fit(X_train, y_train)
        val_preds = ridge.predict(X_val)
        m = calculate_metrics(y_val, val_preds)
        if m["mae"] < best_ridge_val_mae:
            best_ridge_val_mae = m["mae"]
            best_ridge_alpha = alpha
            best_ridge_model = ridge

    val_metrics_ridge = calculate_metrics(y_val, best_ridge_model.predict(X_val))

    # Train Compact Decision Tree
    tree_depths = [3, 4, 5, 6]
    best_tree_depth = 5
    best_tree_val_mae = float("inf")
    best_tree_model = None

    for depth in tree_depths:
        tree = PureDecisionTreeRegressor(max_depth=depth, min_samples_split=20)
        tree.fit(X_train, y_train)
        val_preds = tree.predict(X_val)
        m = calculate_metrics(y_val, val_preds)
        if m["mae"] < best_tree_val_mae:
            best_tree_val_mae = m["mae"]
            best_tree_depth = depth
            best_tree_model = tree

    val_metrics_tree = calculate_metrics(y_val, best_tree_model.predict(X_val))

    # Test COVID-19 Lockdown Structural Break on Validation
    _, X_h1_cov, y_h1_cov, _ = build_dataset_for_target(records, target_col=target_col, horizon=1, include_covid_feature=True)
    X_train_cov = [X_h1_cov[i] for i in train_idx]
    X_val_cov = [X_h1_cov[i] for i in val_idx]
    ridge_cov = PureRidgeRegressor(alpha=best_ridge_alpha)
    ridge_cov.fit(X_train_cov, y_train)
    val_metrics_ridge_cov = calculate_metrics(y_val, ridge_cov.predict(X_val_cov))

    non_lockdown_train_idx = [
        i for i, d in enumerate(dates_h1)
        if d <= "2021-12-31" and not ("2020-03-24" <= d <= "2020-05-31")
    ]
    X_train_no_lockdown = [X_h1[i] for i in non_lockdown_train_idx]
    y_train_no_lockdown = [y_h1[i] for i in non_lockdown_train_idx]
    ridge_no_lockdown = PureRidgeRegressor(alpha=best_ridge_alpha)
    ridge_no_lockdown.fit(X_train_no_lockdown, y_train_no_lockdown)
    val_metrics_ridge_no_lockdown = calculate_metrics(y_val, ridge_no_lockdown.predict(X_val))

    print(f"\n--- 2. 2022 VALIDATION COMPARISON (DAY 1 AHEAD) [{unit_label}] ---")
    print(f"  Baseline (Day-1 Persistence):  MAE = {val_metrics_persist['mae']:.2f}, RMSE = {val_metrics_persist['rmse']:.2f}, MAPE = {val_metrics_persist['mape']:.2f}%")
    print(f"  Baseline (Seasonal-Naive t-7): MAE = {val_metrics_snaive['mae']:.2f}, RMSE = {val_metrics_snaive['rmse']:.2f}, MAPE = {val_metrics_snaive['mape']:.2f}%")
    print(f"  Ridge Regressor (alpha={best_ridge_alpha}):   MAE = {val_metrics_ridge['mae']:.2f}, RMSE = {val_metrics_ridge['rmse']:.2f}, MAPE = {val_metrics_ridge['mape']:.2f}%")
    print(f"  Decision Tree (depth={best_tree_depth}):      MAE = {val_metrics_tree['mae']:.2f}, RMSE = {val_metrics_tree['rmse']:.2f}, MAPE = {val_metrics_tree['mape']:.2f}%")
    print(f"  Ridge + COVID Feature:         MAE = {val_metrics_ridge_cov['mae']:.2f}, RMSE = {val_metrics_ridge_cov['rmse']:.2f}, MAPE = {val_metrics_ridge_cov['mape']:.2f}%")
    print(f"  Ridge Excluding 2020 Lockdown: MAE = {val_metrics_ridge_no_lockdown['mae']:.2f}, RMSE = {val_metrics_ridge_no_lockdown['rmse']:.2f}, MAPE = {val_metrics_ridge_no_lockdown['mape']:.2f}%")

    # 4. Fallback Selection Decision
    fallback_activated = False
    if val_metrics_ridge["mae"] >= val_metrics_persist["mae"]:
        fallback_activated = True
        selected_model_name = "Persistence"
        active_model = None
        print("\n[FALLBACK GATEKEEPER]: ML model failed to beat Persistence on validation. Retaining Persistence!")
    else:
        selected_model_name = "RidgeRegressor"
        active_model = best_ridge_model
        improvement_pct = (1.0 - val_metrics_ridge['mae'] / val_metrics_persist['mae']) * 100.0
        print(f"\n[MODEL SELECTION]: Ridge Regression won validation with MAE {val_metrics_ridge['mae']:.2f} {unit_label} vs Persistence {val_metrics_persist['mae']:.2f} {unit_label} ({improvement_pct:.1f}% improvement).")

    # 5. Evaluate on Final Holdout (Frozen Model)
    y_pred_holdout_persist = [row[0] for row in X_holdout]
    y_pred_holdout_snaive = [row[2] for row in X_holdout]
    y_pred_holdout_ridge = best_ridge_model.predict(X_holdout)
    y_pred_holdout_tree = best_tree_model.predict(X_holdout)

    holdout_metrics_persist = calculate_metrics(y_holdout, y_pred_holdout_persist)
    holdout_metrics_snaive = calculate_metrics(y_holdout, y_pred_holdout_snaive)
    holdout_metrics_ridge = calculate_metrics(y_holdout, y_pred_holdout_ridge)
    holdout_metrics_tree = calculate_metrics(y_holdout, y_pred_holdout_tree)

    print(f"\n--- 3. FINAL HOLDOUT (2023 - APR 2024) FROZEN EVALUATION [{unit_label}] ---")
    print(f"  Day-1 Persistence:  MAE = {holdout_metrics_persist['mae']:.2f}, RMSE = {holdout_metrics_persist['rmse']:.2f}, MAPE = {holdout_metrics_persist['mape']:.2f}%")
    print(f"  Seasonal-Naive:     MAE = {holdout_metrics_snaive['mae']:.2f}, RMSE = {holdout_metrics_snaive['rmse']:.2f}, MAPE = {holdout_metrics_snaive['mape']:.2f}%")
    print(f"  Ridge Regression:   MAE = {holdout_metrics_ridge['mae']:.2f}, RMSE = {holdout_metrics_ridge['rmse']:.2f}, MAPE = {holdout_metrics_ridge['mape']:.2f}%")
    print(f"  Decision Tree:      MAE = {holdout_metrics_tree['mae']:.2f}, RMSE = {holdout_metrics_tree['rmse']:.2f}, MAPE = {holdout_metrics_tree['mape']:.2f}%")
    improvement_holdout = (1.0 - holdout_metrics_ridge['mae'] / holdout_metrics_persist['mae']) * 100.0
    print(f"  Holdout Improvement vs Persistence: {improvement_holdout:.2f}% MAE reduction")

    # Holdout Error Breakdown by Year
    idx_2023 = [i for i, d in enumerate(dates_holdout) if d.startswith("2023")]
    idx_2024 = [i for i, d in enumerate(dates_holdout) if d.startswith("2024")]
    
    breakdown_2023 = {
        "persistence": calculate_metrics([y_holdout[i] for i in idx_2023], [y_pred_holdout_persist[i] for i in idx_2023]),
        "ridge": calculate_metrics([y_holdout[i] for i in idx_2023], [y_pred_holdout_ridge[i] for i in idx_2023])
    }
    breakdown_2024 = {
        "persistence": calculate_metrics([y_holdout[i] for i in idx_2024], [y_pred_holdout_persist[i] for i in idx_2024]),
        "ridge": calculate_metrics([y_holdout[i] for i in idx_2024], [y_pred_holdout_ridge[i] for i in idx_2024])
    }

    # Seasonal breakdown (Summer May-Jun vs Winter Dec-Jan)
    idx_summer = [i for i, d in enumerate(dates_holdout) if d[5:7] in ("05", "06")]
    idx_winter = [i for i, d in enumerate(dates_holdout) if d[5:7] in ("12", "01")]
    breakdown_summer = {
        "persistence": calculate_metrics([y_holdout[i] for i in idx_summer], [y_pred_holdout_persist[i] for i in idx_summer]),
        "ridge": calculate_metrics([y_holdout[i] for i in idx_summer], [y_pred_holdout_ridge[i] for i in idx_summer])
    }
    breakdown_winter = {
        "persistence": calculate_metrics([y_holdout[i] for i in idx_winter], [y_pred_holdout_persist[i] for i in idx_winter]),
        "ridge": calculate_metrics([y_holdout[i] for i in idx_winter], [y_pred_holdout_ridge[i] for i in idx_winter])
    }

    # 6. Multi-Horizon Forecasting (H = 1 to 7 Days Ahead Direct Models)
    print(f"\n--- 4. MULTI-HORIZON 7-DAY FORECASTING (DIRECT MODELS) [{unit_label}] ---")
    multi_horizon_results = {}
    direct_ridge_models = {}

    for h in range(1, 8):
        d_h, X_h, y_h, _ = build_dataset_for_target(records, target_col=target_col, horizon=h, include_covid_feature=False)
        tr_i = [i for i, d in enumerate(d_h) if d <= "2021-12-31"]
        vl_i = [i for i, d in enumerate(d_h) if "2022-01-01" <= d <= "2022-12-31"]
        ho_i = [i for i, d in enumerate(d_h) if d >= "2023-01-01"]

        X_tr = [X_h[i] for i in tr_i]
        y_tr = [y_h[i] for i in tr_i]
        X_vl = [X_h[i] for i in vl_i]
        y_vl = [y_h[i] for i in vl_i]
        X_ho = [X_h[i] for i in ho_i]
        y_ho = [y_h[i] for i in ho_i]

        # Persistence for horizon h (most recent observation at forecast time, which is t-h)
        # Note: In feature row, index 0 is lag_h = y(t - h)
        y_p_ho = [row[0] for row in X_ho]
        # Seasonal Naive for horizon h: index 2 is lag_7 = y(t - 7) (available for all h <= 7)
        y_sn_ho = [row[2] for row in X_ho]

        m_persist_ho = calculate_metrics(y_ho, y_p_ho)
        m_snaive_ho = calculate_metrics(y_ho, y_sn_ho)

        # Train Ridge for horizon h
        r_model = PureRidgeRegressor(alpha=best_ridge_alpha)
        r_model.fit(X_tr, y_tr)
        preds_ho = r_model.predict(X_ho)
        m_ridge_ho = calculate_metrics(y_ho, preds_ho)

        direct_ridge_models[h] = r_model
        multi_horizon_results[f"horizon_{h}"] = {
            "horizon_days": h,
            "persistence_holdout": m_persist_ho,
            "seasonal_naive_holdout": m_snaive_ho,
            "ridge_holdout": m_ridge_ho,
            "mae_reduction_vs_persistence_pct": round((1.0 - m_ridge_ho["mae"] / m_persist_ho["mae"]) * 100.0, 2),
            "mae_reduction_vs_snaive_pct": round((1.0 - m_ridge_ho["mae"] / m_snaive_ho["mae"]) * 100.0, 2)
        }
        print(f"  Day {h} Ahead: Persistence MAE = {m_persist_ho['mae']:.2f} | Seasonal Naive = {m_snaive_ho['mae']:.2f} | Ridge MAE = {m_ridge_ho['mae']:.2f} ({multi_horizon_results[f'horizon_{h}']['mae_reduction_vs_persistence_pct']}% vs persist)")

    # Serialize Best Models
    os.makedirs(MODELS_DIR, exist_ok=True)
    target_slug = "energy" if "energy" in target_col else "peak"
    model_artifact_path = os.path.join(MODELS_DIR, f"certified_{target_slug}_model.json")
    
    model_payload = {
        "target": target_col,
        "target_slug": target_slug,
        "trained_date": datetime.datetime.now().isoformat(),
        "selected_model": selected_model_name,
        "best_alpha": best_ridge_alpha,
        "feature_names": feat_names,
        "h1_model": best_ridge_model.to_dict(),
        "direct_models": {str(h): direct_ridge_models[h].to_dict() for h in range(1, 8)},
        "validation_metrics": val_metrics_ridge,
        "holdout_metrics": holdout_metrics_ridge,
        "validation_persistence_metrics": val_metrics_persist,
        "holdout_persistence_metrics": holdout_metrics_persist
    }
    with open(model_artifact_path, "w") as f:
        json.dump(model_payload, f, indent=2)
    print(f"\nSaved certified model artifact to: {model_artifact_path}")

    return {
        "target": target_col,
        "benchmarks": benchmarks,
        "validation": {
            "persistence": val_metrics_persist,
            "seasonal_naive": val_metrics_snaive,
            "ridge": val_metrics_ridge,
            "decision_tree": val_metrics_tree,
            "ridge_with_covid_feature": val_metrics_ridge_cov,
            "ridge_excluding_2020_lockdown": val_metrics_ridge_no_lockdown
        },
        "holdout": {
            "persistence": holdout_metrics_persist,
            "seasonal_naive": holdout_metrics_snaive,
            "ridge": holdout_metrics_ridge,
            "decision_tree": holdout_metrics_tree,
            "breakdown_2023": breakdown_2023,
            "breakdown_2024": breakdown_2024,
            "breakdown_summer": breakdown_summer,
            "breakdown_winter": breakdown_winter
        },
        "multi_horizon_7day": multi_horizon_results,
        "selected_model": selected_model_name,
        "fallback_activated": fallback_activated
    }


def main():
    print("=" * 60)
    print("EnergySense Phase 2: Forecasting Engine & Model Training")
    print("=" * 60)
    
    records = load_clean_data(DB_PATH)
    print(f"Loaded {len(records)} clean daily records from SQLite ({DB_PATH}).")
    
    # 1. Primary Target: energy_met_mu
    primary_results = run_pipeline(records, target_col="energy_met_mu")
    
    # 2. Secondary Target: peak_met_mw
    secondary_results = run_pipeline(records, target_col="peak_met_mw")

    # Combine into evaluation report JSON
    final_output = {
        "pipeline_version": "2.0.0",
        "timestamp": datetime.datetime.now().isoformat(),
        "primary_target_energy": primary_results,
        "secondary_target_peak": secondary_results
    }
    
    with open(RESULTS_PATH, "w") as f:
        json.dump(final_output, f, indent=2)
    print(f"\nMachine-readable evaluation saved to: {RESULTS_PATH}")
    print("\nPhase 2 training execution finished successfully.")

if __name__ == "__main__":
    main()
