"""
Unit Tests for Phase 2 Forecasting Engine & Model Training
Tests calendar lag correctness, leakage prevention, chronological splitting,
metric calculations, model serialization, origin-aligned multi-horizon integrity,
artifact inference matching, and holdout date accounting.
"""

import os
import json
import math
import sqlite3
import datetime
import unittest

from scripts.train_forecast_model import (
    DB_PATH,
    MODELS_DIR,
    RESULTS_PATH,
    load_clean_data,
    extract_origin_features,
    calculate_metrics,
    StandardFeatureScaler,
    PureRidgeRegressor,
    PureDecisionTreeRegressor,
    audit_benchmark_reproduction
)

class TestForecastingPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = load_clean_data(DB_PATH)
        cls.date_map = {r["dt"]: r["energy_met_mu"] for r in cls.records if r["energy_met_mu"] is not None}

    def test_calendar_lag_correctness(self):
        """Verify lags reflect actual calendar offsets, never row-shifted approximations."""
        missing_dt = datetime.date(2023, 3, 30)
        self.assertNotIn(missing_dt, self.date_map, "2023-03-30 must be missing in canonical database")

        # For origin 2023-03-30 (which is missing), no forecast can be issued
        feats_missing_origin = extract_origin_features(missing_dt, h=1, date_map=self.date_map)
        self.assertIsNone(feats_missing_origin, "Missing origin date must return None features")

        # For origin 2023-03-31, D-1 is 2023-03-30 (missing), so features must return None
        origin_31 = datetime.date(2023, 3, 31)
        feats_origin_31 = extract_origin_features(origin_31, h=1, date_map=self.date_map)
        self.assertIsNone(feats_origin_31, "Origin 2023-03-31 must be None because D-1 (2023-03-30) is missing")

    def test_holdout_date_accounting_completeness(self):
        """Verify exact accounting of 483 holdout DB rows vs 477 evaluated H=1 days."""
        holdout_records = [r for r in self.records if r["dt"] >= datetime.date(2023, 1, 1)]
        self.assertEqual(len(holdout_records), 483, "Holdout must contain 483 valid rows in SQLite")

        valid_h1_dates = []
        omitted_dates = []
        for r in holdout_records:
            target_dt = r["dt"]
            D = target_dt - datetime.timedelta(days=1)
            feats = extract_origin_features(D, h=1, date_map=self.date_map)
            if feats is not None:
                valid_h1_dates.append(r["date"])
            else:
                omitted_dates.append(r["date"])

        self.assertEqual(len(valid_h1_dates), 477, "Evaluated H=1 holdout dates must be exactly 477")
        self.assertEqual(len(omitted_dates), 6, "Omitted dates must be exactly 6")
        expected_omitted = ['2023-03-31', '2023-04-01', '2023-04-06', '2023-04-13', '2023-04-20', '2023-04-27']
        self.assertEqual(sorted(omitted_dates), expected_omitted)

    def test_chronological_splitting_integrity(self):
        """Verify train, validation, and holdout splits are strictly chronological with zero overlap."""
        all_dts = sorted(list(self.date_map.keys()))
        train_dates = [d for d in all_dts if d <= datetime.date(2021, 12, 31)]
        val_dates = [d for d in all_dts if d.year == 2022]
        holdout_dates = [d for d in all_dts if d >= datetime.date(2023, 1, 1)]

        self.assertGreater(len(train_dates), 2500)
        self.assertGreater(len(val_dates), 300)
        self.assertGreater(len(holdout_dates), 400)

        train_set = set(train_dates)
        val_set = set(val_dates)
        holdout_set = set(holdout_dates)

        self.assertTrue(train_set.isdisjoint(val_set))
        self.assertTrue(val_set.isdisjoint(holdout_set))
        self.assertTrue(train_set.isdisjoint(holdout_set))
        self.assertLess(max(train_dates), min(val_dates))
        self.assertLess(max(val_dates), min(holdout_dates))

    def test_leakage_prevention_in_feature_scaling(self):
        """Ensure feature scaler parameters are fit strictly on training data."""
        X_toy_train = [[1.0, 10.0], [2.0, 20.0], [3.0, 30.0]]
        X_toy_val = [[10.0, 100.0], [20.0, 200.0]]

        scaler = StandardFeatureScaler()
        scaler.fit(X_toy_train)

        self.assertAlmostEqual(scaler.means[0], 2.0, places=4)
        self.assertAlmostEqual(scaler.means[1], 20.0, places=4)
        self.assertAlmostEqual(scaler.stds[0], 1.0, places=4)
        self.assertAlmostEqual(scaler.stds[1], 10.0, places=4)

        X_val_scaled = scaler.transform(X_toy_val)
        self.assertAlmostEqual(scaler.means[0], 2.0, places=4)
        self.assertAlmostEqual(X_val_scaled[0][0], (10.0 - 2.0) / 1.0, places=4)
        self.assertAlmostEqual(X_val_scaled[0][1], (100.0 - 20.0) / 10.0, places=4)

    def test_origin_aligned_seven_day_forecast_integrity(self):
        """Verify that multi-horizon forecasting uses only data available on or before origin D."""
        D = datetime.date(2023, 5, 10)
        self.assertIn(D, self.date_map)

        for h in range(1, 8):
            target_dt = D + datetime.timedelta(days=h)
            feats = extract_origin_features(D, h, self.date_map)
            self.assertIsNotNone(feats)
            
            # Feature check:
            # feats[0] is y(D)
            self.assertEqual(feats[0], self.date_map[D])
            # feats[1] is y(D-1)
            self.assertEqual(feats[1], self.date_map[D - datetime.timedelta(days=1)])
            # feats[2] is y(target_dt - 7) = y(D + h - 7)
            snaive_dt = target_dt - datetime.timedelta(days=7)
            self.assertLessEqual(snaive_dt, D, "Seasonal-Naive lag must be on or before origin D")
            self.assertEqual(feats[2], self.date_map[snaive_dt])

    def test_metric_calculations_and_edge_cases(self):
        """Verify MAE, RMSE, and MAPE calculations with denominator edge cases."""
        y_true = [100.0, 200.0, 300.0]
        y_pred = [110.0, 190.0, 300.0]

        metrics = calculate_metrics(y_true, y_pred)
        self.assertAlmostEqual(metrics["mae"], 6.6667, places=3)
        self.assertAlmostEqual(metrics["rmse"], 8.1650, places=3)
        self.assertAlmostEqual(metrics["mape"], 5.0, places=3)
        self.assertEqual(metrics["count"], 3)

        zero_true = [0.0, 100.0]
        zero_pred = [10.0, 110.0]
        zero_metrics = calculate_metrics(zero_true, zero_pred)
        self.assertFalse(math.isinf(zero_metrics["mape"]))

    def test_model_serialization_and_reproducibility(self):
        """Verify models serialize to JSON and reload with identical predictions."""
        X_toy = [[1.0, 2.0], [2.0, 3.0], [3.0, 5.0], [4.0, 7.0], [5.0, 11.0]]
        y_toy = [10.0, 20.0, 30.0, 40.0, 50.0]

        ridge = PureRidgeRegressor(alpha=1.0)
        ridge.fit(X_toy, y_toy)
        orig_preds = ridge.predict(X_toy)

        ridge_dict = ridge.to_dict()
        reloaded_ridge = PureRidgeRegressor.from_dict(ridge_dict)
        reloaded_preds = reloaded_ridge.predict(X_toy)

        for p1, p2 in zip(orig_preds, reloaded_preds):
            self.assertAlmostEqual(p1, p2, places=6)

    def test_json_artifact_inference_matches_training(self):
        """Verify certified model JSON artifact reproduces reported evaluation metrics."""
        energy_model_file = os.path.join(MODELS_DIR, "certified_energy_model.json")
        self.assertTrue(os.path.exists(energy_model_file))

        with open(energy_model_file, "r") as f:
            art = json.load(f)

        self.assertEqual(art["target"], "energy_met_mu")
        self.assertEqual(art["selected_model"], "RidgeRegressor")
        self.assertIn("h1_model", art)
        self.assertIn("direct_models", art)
        self.assertEqual(len(art["direct_models"]), 7)

        # Re-instantiate H1 model from JSON
        h1_reloaded = PureRidgeRegressor.from_dict(art["h1_model"])

        # Test inference on holdout
        X_ho, y_ho = [], []
        for r in self.records:
            target_dt = r["dt"]
            if target_dt < datetime.date(2023, 1, 1):
                continue
            D = target_dt - datetime.timedelta(days=1)
            feats = extract_origin_features(D, h=1, date_map=self.date_map)
            if feats is not None and target_dt in self.date_map:
                X_ho.append(feats)
                y_ho.append(self.date_map[target_dt])

        preds = h1_reloaded.predict(X_ho)
        m = calculate_metrics(y_ho, preds)

        # Compare with metrics stored in artifact
        stored_m = art["h1_holdout_metrics"]
        self.assertAlmostEqual(m["mae"], stored_m["mae"], places=2)
        self.assertAlmostEqual(m["rmse"], stored_m["rmse"], places=2)
        self.assertAlmostEqual(m["mape"], stored_m["mape"], places=2)

    def test_baseline_reproduction_accuracy(self):
        """Verify reproduction of benchmark numbers on 2023-2024 holdout."""
        benchmarks = audit_benchmark_reproduction(self.records, target_col="energy_met_mu")
        m_a = benchmarks["method_A_row_index_shift"]["metrics"]
        self.assertAlmostEqual(m_a["mae"], 89.92, delta=0.1)
        self.assertAlmostEqual(m_a["mape"], 2.08, delta=0.05)

        m_b = benchmarks["method_B_strict_calendar_lag_1"]["metrics"]
        self.assertEqual(m_b["count"], 482)
        self.assertAlmostEqual(m_b["mae"], 89.61, delta=0.1)

if __name__ == "__main__":
    unittest.main()
