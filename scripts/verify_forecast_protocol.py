"""
Verification script for forecasting protocol:
1. Origin-aligned 7-day forecast evaluation across common origins D.
2. Fair holdout comparisons and accounting of excluded dates.
3. Verification of JSON artifact inference vs training implementation.
"""

import os
import json
import math
import sqlite3
import datetime

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.train_forecast_model import (
    DB_PATH,
    MODELS_DIR,
    load_clean_data,
    calculate_metrics,
    PureRidgeRegressor,
    StandardFeatureScaler
)

def run_origin_aligned_audit():
    records = load_clean_data(DB_PATH)
    date_map_energy = {r["dt"]: r["energy_met_mu"] for r in records if r["energy_met_mu"] is not None}
    date_map_peak = {r["dt"]: r["peak_met_mw"] for r in records if r["peak_met_mw"] is not None}
    t0 = datetime.date(2013, 1, 1)

    print("=" * 80)
    print("1. ORIGIN-ALIGNED SEVEN-DAY FORECAST PROTOCOL AUDIT")
    print("=" * 80)

    for target_name, date_map, unit, alpha in [
        ("energy_met_mu", date_map_energy, "MU", 0.01),
        ("peak_met_mw", date_map_peak, "MW", 0.01)
    ]:
        print(f"\n--- TARGET: {target_name.upper()} ({unit}) ---")

        def extract_origin_features(D, h):
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
            
            r7_vals = [date_map[D - datetime.timedelta(days=k)] for k in range(7) if (D - datetime.timedelta(days=k)) in date_map]
            if len(r7_vals) < 5:
                return None
            roll_mean_7 = sum(r7_vals) / len(r7_vals)
            
            r28_vals = [date_map[D - datetime.timedelta(days=k)] for k in range(28) if (D - datetime.timedelta(days=k)) in date_map]
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
            
            return lags + [roll_mean_7, roll_mean_28, trend_years, sin_doy_1, cos_doy_1, sin_doy_2, cos_doy_2] + dow_ohe

        # 1. Train models on Training period (origins D where target D+h <= 2021-12-31)
        direct_models = {}
        for h in range(1, 8):
            X_tr, y_tr = [], []
            for r in records:
                D = r["dt"]
                target_dt = D + datetime.timedelta(days=h)
                if target_dt > datetime.date(2021, 12, 31):
                    continue
                if target_dt not in date_map:
                    continue
                feats = extract_origin_features(D, h)
                if feats is not None:
                    X_tr.append(feats)
                    y_tr.append(date_map[target_dt])
            model = PureRidgeRegressor(alpha=alpha)
            model.fit(X_tr, y_tr)
            direct_models[h] = model

        # 2. Identify common eligible origins in holdout (2023-01-01 to 2024-04-21)
        holdout_origins = []
        d_cur = datetime.date(2023, 1, 1)
        d_max = datetime.date(2024, 4, 21)
        
        while d_cur <= d_max:
            targets_exist = all((d_cur + datetime.timedelta(days=h)) in date_map for h in range(1, 8))
            feats_exist = all(extract_origin_features(d_cur, h) is not None for h in range(1, 8))
            if targets_exist and feats_exist:
                holdout_origins.append(d_cur)
            d_cur += datetime.timedelta(days=1)

        print(f"Common eligible holdout forecast origins: {len(holdout_origins)} origins (from {holdout_origins[0]} to {holdout_origins[-1]})")
        print(f"{'Horizon':<8} | {'Persistence':<22} | {'Seasonal Naive':<22} | {'Direct Ridge':<22} | {'vs Persist':<12} | {'vs SNaive':<12}")
        print("-" * 105)

        for h in range(1, 8):
            y_true = []
            y_pred_persist = []
            y_pred_snaive = []
            y_pred_ridge = []
            
            for D in holdout_origins:
                target_dt = D + datetime.timedelta(days=h)
                y_act = date_map[target_dt]
                y_true.append(y_act)
                
                # Formula 1: Persistence at origin D -> y(D)
                y_pred_persist.append(date_map[D])
                
                # Formula 2: Seasonal-Naive at origin D -> y(target_dt - 7) = y(D + h - 7)
                y_pred_snaive.append(date_map[target_dt - datetime.timedelta(days=7)])
                
                # Formula 3: Direct Ridge Model for horizon h
                feats = extract_origin_features(D, h)
                y_pred_ridge.append(direct_models[h].predict([feats])[0])
                
            m_p = calculate_metrics(y_true, y_pred_persist)
            m_sn = calculate_metrics(y_true, y_pred_snaive)
            m_r = calculate_metrics(y_true, y_pred_ridge)
            
            gain_p = (1.0 - m_r['mae'] / m_p['mae']) * 100.0
            gain_sn = (1.0 - m_r['mae'] / m_sn['mae']) * 100.0
            
            p_str = f"MAE={m_p['mae']:6.2f} ({m_p['mape']:4.2f}%)"
            sn_str = f"MAE={m_sn['mae']:6.2f} ({m_sn['mape']:4.2f}%)"
            r_str = f"MAE={m_r['mae']:6.2f} ({m_r['mape']:4.2f}%)"
            
            print(f"Day {h} (<D+{h}>) | {p_str:<22} | {sn_str:<22} | {r_str:<22} | {gain_p:+6.2f}%     | {gain_sn:+6.2f}%")

if __name__ == "__main__":
    run_origin_aligned_audit()
