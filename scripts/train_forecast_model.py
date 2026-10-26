"""
Phase 2: Forecasting Engine & Model Training Pipeline (Audited Protocol)
EnergySense / GridSense Platform

This script implements a reproducible, zero-external-dependency forecasting engine:
1. Baselines:
   - Day-1 Persistence: y(t-1)
   - Seasonal-Naive: y(t-7)
   - Multi-Horizon Origin-Aligned Persistence: y(D) for all D+h
   - Multi-Horizon Origin-Aligned Seasonal-Naive: y(D+h-7) for D+h
2. Features: Leakage-safe calendar features, exact calendar lags (D, D-1, D+h-7, D+h-14, D+h-21, D+h-28),
   and rolling statistics calculated strictly from observations available on or before origin D.
3. Models: Closed-form L2 Ridge Regression (pure Python Gaussian elimination solver)
   and Compact Regression Tree (variance reduction).
4. Targets: National Daily Energy Met (MU) [Primary] and Peak Met (MW) [Secondary].
5. Evaluation Protocols:
   - Protocol 1: Rolling One-Day-Ahead Forecast (H=1) across target dates 2023-2024.
   - Protocol 2: Origin-Aligned Seven-Day Forecast issued at origin D for D+1..D+7 on common holdout origins.
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
    
    BT = matrix_transpose(B)
    return [[sum(A[i][k] * BT[j][k] for k in range(n_cols_A)) for j in range(n_cols_B)] for i in range(n_rows_A)]

def matrix_vector_multiply(A: List[List[float]], v: List[float]) -> List[float]:
    n_cols = len(v)
    return [sum(row[k] * v[k] for k in range(n_cols)) for row in A]

def solve_linear_system(A: List[List[float]], b: List[float]) -> List[float]:
    """Gaussian elimination with partial pivoting."""
    n = len(A)
    M = [A[i][:] + [b[i]] for i in range(n)]
    
    for i in range(n):
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
        
        self.intercept = sum(y) / n_samples
        y_centered = [yi - self.intercept for yi in y]
        
        self.scaler.fit(X)
        X_scaled = self.scaler.transform(X)
        
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
# 4. DATA LOADING & ORIGIN-CENTRIC FEATURE ENGINEERING
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

def extract_origin_features(
    D: datetime.date,
    h: int,
    date_map: Dict[datetime.date, float],
    t0: datetime.date = datetime.date(2013, 1, 1),
    include_covid_feature: bool = False
) -> Optional[List[float]]:
    """
    Extracts features available strictly on or before forecast origin date D
    to predict target date T = D + h.
    
    Lags available at origin D:
      - y(D): most recent known observation at origin D
      - y(D - 1): prior day observation
      - y(T - 7) = y(D + h - 7): same day-of-week 1 week prior to target. (Known at D because h <= 7)
      - y(T - 14) = y(D + h - 14): same day-of-week 2 weeks prior
      - y(T - 21) = y(D + h - 21): same day-of-week 3 weeks prior
      - y(T - 28) = y(D + h - 28): same day-of-week 4 weeks prior
    Rolling statistics at origin D:
      - 7-day rolling mean of available days in [D - 6 .. D] (requires >= 5)
      - 28-day rolling mean of available days in [D - 27 .. D] (requires >= 20)
    Target calendar features of T = D + h:
      - Trend (years from 2013-01-01)
      - Fourier annual seasonality (1st and 2nd harmonics)
      - Day of week (Mon..Sat one-hot)
    """
    target_dt = D + datetime.timedelta(days=h)
    
    lag_dates = [
        D,
        D - datetime.timedelta(days=1),
        target_dt - datetime.timedelta(days=7),
        target_dt - datetime.timedelta(days=14),
        target_dt - datetime.timedelta(days=21),
        target_dt - datetime.timedelta(days=28)
    ]
    if not all(ld in date_map for ld in lag_dates):
        return None
    lags = [date_map[ld] for ld in lag_dates]
    
    r7_vals = [date_map[D - datetime.timedelta(days=k)] 
               for k in range(7) if (D - datetime.timedelta(days=k)) in date_map]
    if len(r7_vals) < 5:
        return None
    roll_mean_7 = sum(r7_vals) / len(r7_vals)
    
    r28_vals = [date_map[D - datetime.timedelta(days=k)] 
                for k in range(28) if (D - datetime.timedelta(days=k)) in date_map]
    if len(r28_vals) < 20:
        return None
    roll_mean_28 = sum(r28_vals) / len(r28_vals)
    
    trend_years = (target_dt - t0).days / 365.25
    doy = target_dt.timetuple().tm_yday
    sin_doy_1 = math.sin(2.0 * math.pi * doy / 365.25)
    cos_doy_1 = math.cos(2.0 * math.pi * doy / 365.25)
    sin_doy_2 = math.sin(4.0 * math.pi * doy / 365.25)
    cos_doy_2 = math.cos(4.0 * math.pi * doy / 365.25)
    
    dow = target_dt.weekday()
    dow_ohe = [1.0 if dow == k else 0.0 for k in range(6)]
    
    row = lags + [roll_mean_7, roll_mean_28, trend_years, sin_doy_1, cos_doy_1, sin_doy_2, cos_doy_2] + dow_ohe
    if include_covid_feature:
        is_lockdown = 1.0 if datetime.date(2020, 3, 24) <= target_dt <= datetime.date(2020, 5, 31) else 0.0
        row.append(is_lockdown)
        
    return row

def get_feature_names(h: int, include_covid_feature: bool = False) -> List[str]:
    names = [
        "lag_origin_D", "lag_origin_D_minus_1",
        f"lag_target_minus_7", f"lag_target_minus_14", f"lag_target_minus_21", f"lag_target_minus_28",
        "roll_mean_7_origin", "roll_mean_28_origin",
        "trend_years",
        "sin_doy_1", "cos_doy_1", "sin_doy_2", "cos_doy_2",
        "dow_mon", "dow_tue", "dow_wed", "dow_thu", "dow_fri", "dow_sat"
    ]
    if include_covid_feature:
        names.append("is_lockdown_2020")
    return names


# ============================================================================
# 5. SPLIT & BENCHMARK REPRODUCTION AUDIT
# ============================================================================

def audit_benchmark_reproduction(records: List[Dict[str, Any]], target_col: str = "energy_met_mu") -> Dict[str, Any]:
    holdout_start = datetime.date(2023, 1, 1)
    holdout_end = datetime.date(2024, 4, 28)
    
    date_map = {r["dt"]: r[target_col] for r in records if r[target_col] is not None}
    rec_in_range = [r for r in records if holdout_start <= r["dt"] <= holdout_end and r[target_col] is not None]
    
    # Method A: Row-index shift (483 days)
    y_true_A, y_pred_persist_A = [], []
    for r in rec_in_range:
        idx = records.index(r)
        if idx > 0 and records[idx - 1][target_col] is not None:
            y_true_A.append(r[target_col])
            y_pred_persist_A.append(records[idx - 1][target_col])
    metrics_A = calculate_metrics(y_true_A, y_pred_persist_A)

    # Method B: Strict calendar t-1 (482 days)
    y_true_B, y_pred_persist_B = [], []
    for r in rec_in_range:
        prev_dt = r["dt"] - datetime.timedelta(days=1)
        if prev_dt in date_map:
            y_true_B.append(r[target_col])
            y_pred_persist_B.append(date_map[prev_dt])
    metrics_B = calculate_metrics(y_true_B, y_pred_persist_B)

    # Method C: Common valid set where both strict t-1 and t-7 exist (481 days)
    y_true_C, y_pred_persist_C, y_pred_snaive_C = [], [], []
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
            "evaluated_days": len(y_true_A),
            "excluded_days": 0,
            "metrics": metrics_A
        },
        "method_B_strict_calendar_lag_1": {
            "description": "Strict calendar t-1 (excludes 2023-03-31 because 2023-03-30 is absent)",
            "evaluated_days": len(y_true_B),
            "excluded_days": 1,
            "excluded_dates": ["2023-03-31"],
            "metrics": metrics_B
        },
        "method_C_common_valid_evaluation_set": {
            "description": "Common dates where both strict t-1 and t-7 exist (excludes 2023-03-31 and 2023-04-06)",
            "evaluated_days": len(y_true_C),
            "excluded_days": 2,
            "excluded_dates": ["2023-03-31", "2023-04-06"],
            "persistence_metrics": metrics_C_persist,
            "seasonal_naive_metrics": metrics_C_snaive
        }
    }


# ============================================================================
# 6. TRAINING & EVALUATION PIPELINE
# ============================================================================

def run_audited_pipeline(records: List[Dict[str, Any]], target_col: str = "energy_met_mu") -> Dict[str, Any]:
    unit_label = "MU" if "energy" in target_col else "MW"
    print(f"\n=======================================================")
    print(f"RUNNING AUDITED FORECAST PIPELINE: {target_col.upper()} ({unit_label})")
    print(f"=======================================================")

    date_map = {r["dt"]: r[target_col] for r in records if r[target_col] is not None}
    benchmarks = audit_benchmark_reproduction(records, target_col=target_col)

    # ----------------------------------------------------
    # PROTOCOL 1: ROLLING ONE-DAY-AHEAD EVALUATION (H=1)
    # ----------------------------------------------------
    # For every date t, origin is D = t - 1
    # Train: target dates <= 2021-12-31
    # Val: target dates in 2022
    # Holdout: target dates in 2023-01-01 to 2024-04-28
    X_tr_h1, y_tr_h1, d_tr_h1 = [], [], []
    X_vl_h1, y_vl_h1, d_vl_h1 = [], [], []
    X_ho_h1, y_ho_h1, d_ho_h1 = [], [], []

    for r in records:
        target_dt = r["dt"]
        D = target_dt - datetime.timedelta(days=1)
        feats = extract_origin_features(D, h=1, date_map=date_map)
        if feats is None or target_dt not in date_map:
            continue
        
        y_val = date_map[target_dt]
        d_str = r["date"]
        
        if target_dt <= datetime.date(2021, 12, 31):
            X_tr_h1.append(feats)
            y_tr_h1.append(y_val)
            d_tr_h1.append(d_str)
        elif target_dt.year == 2022:
            X_vl_h1.append(feats)
            y_vl_h1.append(y_val)
            d_vl_h1.append(d_str)
        elif target_dt >= datetime.date(2023, 1, 1):
            X_ho_h1.append(feats)
            y_ho_h1.append(y_val)
            d_ho_h1.append(d_str)

    print(f"\nProtocol 1 (Rolling Day-Ahead H=1) Sample Counts:")
    print(f"  Training (2013-2021):     {len(X_tr_h1)} samples ({d_tr_h1[0]} to {d_tr_h1[-1]})")
    print(f"  Validation (2022):        {len(X_vl_h1)} samples ({d_vl_h1[0]} to {d_vl_h1[-1]})")
    print(f"  Holdout (2023-2024):      {len(X_ho_h1)} samples ({d_ho_h1[0]} to {d_ho_h1[-1]})")

    # In H1 feature row: index 0 is y(D) = y(t-1), index 2 is y(t-7)
    y_pred_val_persist = [row[0] for row in X_vl_h1]
    y_pred_val_snaive = [row[2] for row in X_vl_h1]
    m_val_persist = calculate_metrics(y_vl_h1, y_pred_val_persist)
    m_val_snaive = calculate_metrics(y_vl_h1, y_pred_val_snaive)

    # Train Ridge across alpha grid on Train set only
    alphas = [0.01, 0.1, 1.0, 5.0, 10.0, 50.0, 100.0]
    best_alpha = 1.0
    best_val_mae = float("inf")
    best_ridge_h1 = None

    for alpha in alphas:
        r_model = PureRidgeRegressor(alpha=alpha)
        r_model.fit(X_tr_h1, y_tr_h1)
        preds = r_model.predict(X_vl_h1)
        m = calculate_metrics(y_vl_h1, preds)
        if m["mae"] < best_val_mae:
            best_val_mae = m["mae"]
            best_alpha = alpha
            best_ridge_h1 = r_model

    m_val_ridge = calculate_metrics(y_vl_h1, best_ridge_h1.predict(X_vl_h1))

    # Tree candidate on validation
    best_tree_h1 = None
    best_tree_val_mae = float("inf")
    for depth in [3, 4, 5, 6]:
        tree = PureDecisionTreeRegressor(max_depth=depth, min_samples_split=20)
        tree.fit(X_tr_h1, y_tr_h1)
        preds = tree.predict(X_vl_h1)
        m = calculate_metrics(y_vl_h1, preds)
        if m["mae"] < best_tree_val_mae:
            best_tree_val_mae = m["mae"]
            best_tree_h1 = tree
    m_val_tree = calculate_metrics(y_vl_h1, best_tree_h1.predict(X_vl_h1))

    # COVID check on Validation
    X_tr_cov, X_vl_cov = [], []
    for r in records:
        target_dt = r["dt"]
        D = target_dt - datetime.timedelta(days=1)
        feats = extract_origin_features(D, h=1, date_map=date_map, include_covid_feature=True)
        if feats is None or target_dt not in date_map:
            continue
        if target_dt <= datetime.date(2021, 12, 31):
            X_tr_cov.append(feats)
        elif target_dt.year == 2022:
            X_vl_cov.append(feats)
    ridge_cov = PureRidgeRegressor(alpha=best_alpha)
    ridge_cov.fit(X_tr_cov, y_tr_h1)
    m_val_covid = calculate_metrics(y_vl_h1, ridge_cov.predict(X_vl_cov))

    # Decision on Fallback
    fallback_activated = False
    if m_val_ridge["mae"] >= m_val_persist["mae"]:
        fallback_activated = True
        selected_model_name = "Persistence"
    else:
        selected_model_name = "RidgeRegressor"

    # Evaluate on Holdout (H=1)
    y_pred_ho_persist = [row[0] for row in X_ho_h1]
    y_pred_ho_snaive = [row[2] for row in X_ho_h1]
    y_pred_ho_ridge = best_ridge_h1.predict(X_ho_h1)
    y_pred_ho_tree = best_tree_h1.predict(X_ho_h1)

    m_ho_persist = calculate_metrics(y_ho_h1, y_pred_ho_persist)
    m_ho_snaive = calculate_metrics(y_ho_h1, y_pred_ho_snaive)
    m_ho_ridge = calculate_metrics(y_ho_h1, y_pred_ho_ridge)
    m_ho_tree = calculate_metrics(y_ho_h1, y_pred_ho_tree)

    # ------------------------------------------------------------------
    # PROTOCOL 2: ORIGIN-ALIGNED SEVEN-DAY FORECASTING (H = 1 to 7)
    # ------------------------------------------------------------------
    # Train separate direct Ridge models for h in 1..7
    direct_ridge_models = {}
    for h in range(1, 8):
        X_tr, y_tr = [], []
        for r in records:
            D = r["dt"]
            target_dt = D + datetime.timedelta(days=h)
            if target_dt > datetime.date(2021, 12, 31) or target_dt not in date_map:
                continue
            feats = extract_origin_features(D, h, date_map=date_map)
            if feats is not None:
                X_tr.append(feats)
                y_tr.append(date_map[target_dt])
        model = PureRidgeRegressor(alpha=best_alpha)
        model.fit(X_tr, y_tr)
        direct_ridge_models[h] = model

    # Identify common eligible origins in holdout (2023-01-01 to 2024-04-21)
    common_holdout_origins = []
    d_cur = datetime.date(2023, 1, 1)
    d_max = datetime.date(2024, 4, 21)

    while d_cur <= d_max:
        targets_exist = all((d_cur + datetime.timedelta(days=h)) in date_map for h in range(1, 8))
        feats_exist = all(extract_origin_features(d_cur, h, date_map=date_map) is not None for h in range(1, 8))
        if targets_exist and feats_exist:
            common_holdout_origins.append(d_cur)
        d_cur += datetime.timedelta(days=1)

    origin_aligned_results = {}
    for h in range(1, 8):
        y_true = []
        y_pred_persist = []
        y_pred_snaive = []
        y_pred_ridge = []
        
        for D in common_holdout_origins:
            target_dt = D + datetime.timedelta(days=h)
            y_act = date_map[target_dt]
            y_true.append(y_act)
            
            # Baseline 1: y(D)
            y_pred_persist.append(date_map[D])
            # Baseline 2: y(D + h - 7)
            y_pred_snaive.append(date_map[target_dt - datetime.timedelta(days=7)])
            
            feats = extract_origin_features(D, h, date_map=date_map)
            y_pred_ridge.append(direct_ridge_models[h].predict([feats])[0])
            
        m_p = calculate_metrics(y_true, y_pred_persist)
        m_sn = calculate_metrics(y_true, y_pred_snaive)
        m_r = calculate_metrics(y_true, y_pred_ridge)
        
        origin_aligned_results[f"horizon_{h}"] = {
            "horizon_days": h,
            "evaluated_origins_count": len(common_holdout_origins),
            "persistence_metrics": m_p,
            "seasonal_naive_metrics": m_sn,
            "ridge_metrics": m_r,
            "improvement_vs_persistence_pct": round((1.0 - m_r["mae"] / m_p["mae"]) * 100.0, 2),
            "improvement_vs_snaive_pct": round((1.0 - m_r["mae"] / m_sn["mae"]) * 100.0, 2)
        }

    # ----------------------------------------------------
    # SERIALIZE CERTIFIED ARTIFACTS
    # ----------------------------------------------------
    os.makedirs(MODELS_DIR, exist_ok=True)
    target_slug = "energy" if "energy" in target_col else "peak"
    model_artifact_path = os.path.join(MODELS_DIR, f"certified_{target_slug}_model.json")
    
    model_payload = {
        "target": target_col,
        "target_slug": target_slug,
        "trained_date": datetime.datetime.now().isoformat(),
        "selected_model": selected_model_name,
        "best_alpha": best_alpha,
        "feature_names": get_feature_names(h=1),
        "h1_model": best_ridge_h1.to_dict(),
        "direct_models": {str(h): direct_ridge_models[h].to_dict() for h in range(1, 8)},
        "h1_validation_metrics": m_val_ridge,
        "h1_holdout_metrics": m_ho_ridge,
        "h1_validation_persistence_metrics": m_val_persist,
        "h1_holdout_persistence_metrics": m_ho_persist,
        "origin_aligned_7day_holdout": origin_aligned_results
    }
    with open(model_artifact_path, "w") as f:
        json.dump(model_payload, f, indent=2)

    return {
        "target": target_col,
        "benchmarks": benchmarks,
        "h1_rolling_evaluation": {
            "validation": {
                "persistence": m_val_persist,
                "seasonal_naive": m_val_snaive,
                "ridge": m_val_ridge,
                "decision_tree": m_val_tree,
                "ridge_with_covid_feature": m_val_covid
            },
            "holdout": {
                "persistence": m_ho_persist,
                "seasonal_naive": m_ho_snaive,
                "ridge": m_ho_ridge,
                "decision_tree": m_ho_tree,
                "mae_reduction_vs_persistence_pct": round((1.0 - m_ho_ridge["mae"] / m_ho_persist["mae"]) * 100.0, 2),
                "mae_reduction_vs_snaive_pct": round((1.0 - m_ho_ridge["mae"] / m_ho_snaive["mae"]) * 100.0, 2)
            }
        },
        "origin_aligned_7day_evaluation": {
            "eligible_common_origins": len(common_holdout_origins),
            "origin_range": f"{common_holdout_origins[0]} to {common_holdout_origins[-1]}",
            "horizons": origin_aligned_results
        },
        "selected_model": selected_model_name,
        "fallback_activated": fallback_activated
    }

def main():
    print("=" * 70)
    print("EnergySense Phase 2: Forecasting Engine & Audited Verification")
    print("=" * 70)
    records = load_clean_data(DB_PATH)
    
    primary_results = run_audited_pipeline(records, target_col="energy_met_mu")
    secondary_results = run_audited_pipeline(records, target_col="peak_met_mw")

    output = {
        "pipeline_version": "2.1.0-audited",
        "timestamp": datetime.datetime.now().isoformat(),
        "primary_target_energy": primary_results,
        "secondary_target_peak": secondary_results
    }
    with open(RESULTS_PATH, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nAll audited evaluation results saved to: {RESULTS_PATH}")

if __name__ == "__main__":
    main()
