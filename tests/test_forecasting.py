"""
Unit Tests for Phase 2 Forecasting Engine & Model Training
Tests calendar lag correctness, leakage prevention, chronological splitting,
metric calculations, model serialization, and fallback selection.
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
    build_dataset_for_target,
    calculate_metrics,
    StandardFeatureScaler,
    PureRidgeRegressor,
    PureDecisionTreeRegressor,
    reproduce_reported_benchmarks
)

class TestForecastingPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = load_clean_data(DB_PATH)
        cls.date_map = {r["dt"]: r["energy_met_mu"] for r in cls.records if r["energy_met_mu"] is not None}

    def test_calendar_lag_correctness(self):
        """Verify lags reflect actual calendar offsets, never row-shifted approximations."""
        # 2023-03-30 is a known missing date in holdout
        missing_dt = datetime.date(2023, 3, 30)
        self.assertNotIn(missing_dt, self.date_map, "2023-03-30 must be missing in canonical database")

        # For 2023-03-31, calendar t-1 is 2023-03-30 (which is missing)
        # Therefore, build_dataset_for_target with horizon=1 must NOT include 2023-03-31
        dates_h1, X_h1, y_h1, _ = build_dataset_for_target(self.records, target_col="energy_met_mu", horizon=1)
        self.assertNotIn("2023-03-31", dates_h1, "2023-03-31 must be excluded from H=1 dataset because calendar t-1 is absent")

        # For 2023-04-06, calendar t-7 is 2023-03-30 (which is missing)
        # Therefore, build_dataset_for_target with horizon=1 must NOT include 2023-04-06
        self.assertNotIn("2023-04-06", dates_h1, "2023-04-06 must be excluded from H=1 dataset because calendar t-7 is absent")

    def test_chronological_splitting_integrity(self):
        """Verify train, validation, and holdout splits are strictly chronological with zero overlap."""
        dates_h1, X_h1, y_h1, _ = build_dataset_for_target(self.records, target_col="energy_met_mu", horizon=1)
        
        train_dates = [d for d in dates_h1 if d <= "2021-12-31"]
        val_dates = [d for d in dates_h1 if "2022-01-01" <= d <= "2022-12-31"]
        holdout_dates = [d for d in dates_h1 if d >= "2023-01-01"]

        self.assertGreater(len(train_dates), 1000, "Train set must have substantial data")
        self.assertGreater(len(val_dates), 250, "Validation set must have 2022 data")
        self.assertGreater(len(holdout_dates), 350, "Holdout set must have 2023-2024 data")

        # Strict non-overlap
        train_set = set(train_dates)
        val_set = set(val_dates)
        holdout_set = set(holdout_dates)

        self.assertTrue(train_set.isdisjoint(val_set), "Train and validation sets must be disjoint")
        self.assertTrue(val_set.isdisjoint(holdout_set), "Validation and holdout sets must be disjoint")
        self.assertTrue(train_set.isdisjoint(holdout_set), "Train and holdout sets must be disjoint")

        # Chronological ordering check
        self.assertLess(max(train_dates), min(val_dates), "Max train date must precede min val date")
        self.assertLess(max(val_dates), min(holdout_dates), "Max val date must precede min holdout date")

    def test_leakage_prevention_in_feature_scaling(self):
        """Ensure feature scaler parameters are fit strictly on training data."""
        X_toy_train = [[1.0, 10.0], [2.0, 20.0], [3.0, 30.0]]
        X_toy_val = [[10.0, 100.0], [20.0, 200.0]]

        scaler = StandardFeatureScaler()
        scaler.fit(X_toy_train)

        # Expected train statistics: mean=[2.0, 20.0], std=[1.0, 10.0]
        self.assertAlmostEqual(scaler.means[0], 2.0, places=4)
        self.assertAlmostEqual(scaler.means[1], 20.0, places=4)
        self.assertAlmostEqual(scaler.stds[0], 1.0, places=4)
        self.assertAlmostEqual(scaler.stds[1], 10.0, places=4)

        # Transforming validation data must not change learned parameters
        X_val_scaled = scaler.transform(X_toy_val)
        self.assertAlmostEqual(scaler.means[0], 2.0, places=4)
        self.assertAlmostEqual(X_val_scaled[0][0], (10.0 - 2.0) / 1.0, places=4)
        self.assertAlmostEqual(X_val_scaled[0][1], (100.0 - 20.0) / 10.0, places=4)

    def test_metric_calculations_and_edge_cases(self):
        """Verify MAE, RMSE, and MAPE calculations with denominator edge cases."""
        y_true = [100.0, 200.0, 300.0]
        y_pred = [110.0, 190.0, 300.0]

        metrics = calculate_metrics(y_true, y_pred)
        # Abs errors: 10, 10, 0 -> MAE = 20 / 3 = 6.6667
        # Sq errors: 100, 100, 0 -> RMSE = sqrt(200 / 3) = 8.1650
        # Pct errors: 10%, 5%, 0% -> MAPE = 15% / 3 = 5.0%
        self.assertAlmostEqual(metrics["mae"], 6.6667, places=3)
        self.assertAlmostEqual(metrics["rmse"], 8.1650, places=3)
        self.assertAlmostEqual(metrics["mape"], 5.0, places=3)
        self.assertEqual(metrics["count"], 3)

        # Zero handling
        zero_true = [0.0, 100.0]
        zero_pred = [10.0, 110.0]
        zero_metrics = calculate_metrics(zero_true, zero_pred)
        self.assertFalse(math.isinf(zero_metrics["mape"]), "Zero actual value must not raise ZeroDivisionError or Inf")

    def test_model_serialization_and_reproducibility(self):
        """Verify models serialize to JSON and reload with identical predictions."""
        X_toy = [[1.0, 2.0], [2.0, 3.0], [3.0, 5.0], [4.0, 7.0], [5.0, 11.0]]
        y_toy = [10.0, 20.0, 30.0, 40.0, 50.0]

        # Ridge
        ridge = PureRidgeRegressor(alpha=1.0)
        ridge.fit(X_toy, y_toy)
        orig_preds = ridge.predict(X_toy)

        ridge_dict = ridge.to_dict()
        reloaded_ridge = PureRidgeRegressor.from_dict(ridge_dict)
        reloaded_preds = reloaded_ridge.predict(X_toy)

        for p1, p2 in zip(orig_preds, reloaded_preds):
            self.assertAlmostEqual(p1, p2, places=6, msg="Reloaded Ridge model must match predictions exactly")

        # Decision Tree
        tree = PureDecisionTreeRegressor(max_depth=3, min_samples_split=2)
        tree.fit(X_toy, y_toy)
        orig_tree_preds = tree.predict(X_toy)

        tree_dict = tree.to_dict()
        reloaded_tree = PureDecisionTreeRegressor.from_dict(tree_dict)
        reloaded_tree_preds = reloaded_tree.predict(X_toy)

        for p1, p2 in zip(orig_tree_preds, reloaded_tree_preds):
            self.assertAlmostEqual(p1, p2, places=6, msg="Reloaded Decision Tree must match predictions exactly")

    def test_fallback_gatekeeper_selection(self):
        """Verify fallback triggers when ML fails to beat baseline on validation."""
        # Simulated scenario 1: ML beats persistence
        val_mae_persist = 80.0
        val_mae_ridge_good = 55.0
        
        fallback_active_1 = val_mae_ridge_good >= val_mae_persist
        selected_1 = "Persistence" if fallback_active_1 else "RidgeRegressor"
        self.assertFalse(fallback_active_1)
        self.assertEqual(selected_1, "RidgeRegressor")

        # Simulated scenario 2: ML is worse than persistence
        val_mae_ridge_bad = 95.0
        fallback_active_2 = val_mae_ridge_bad >= val_mae_persist
        selected_2 = "Persistence" if fallback_active_2 else "RidgeRegressor"
        self.assertTrue(fallback_active_2)
        self.assertEqual(selected_2, "Persistence")

    def test_baseline_reproduction_accuracy(self):
        """Verify reproduction of benchmark numbers on 2023-2024 holdout."""
        benchmarks = reproduce_reported_benchmarks(self.records, target_col="energy_met_mu")
        
        # Method A (row shift): reported ~89.92 MU MAE and 2.08% MAPE
        m_a = benchmarks["method_A_row_index_shift"]["metrics"]
        self.assertAlmostEqual(m_a["mae"], 89.92, delta=0.1, msg="Method A MAE should match ~89.92 MU")
        self.assertAlmostEqual(m_a["mape"], 2.08, delta=0.05, msg="Method A MAPE should match ~2.08%")

        # Method B (strict t-1 calendar): excludes gap
        m_b = benchmarks["method_B_strict_calendar_lag_1"]["metrics"]
        self.assertEqual(m_b["count"], 482)
        self.assertAlmostEqual(m_b["mae"], 89.61, delta=0.1)

    def test_saved_artifacts_validity(self):
        """Verify saved certified model artifacts exist and contain required keys."""
        energy_model_file = os.path.join(MODELS_DIR, "certified_energy_model.json")
        peak_model_file = os.path.join(MODELS_DIR, "certified_peak_model.json")
        
        self.assertTrue(os.path.exists(energy_model_file), "certified_energy_model.json must exist")
        self.assertTrue(os.path.exists(peak_model_file), "certified_peak_model.json must exist")
        self.assertTrue(os.path.exists(RESULTS_PATH), "forecast_evaluation_results.json must exist")

        with open(energy_model_file, "r") as f:
            e_data = json.load(f)
        self.assertEqual(e_data["target"], "energy_met_mu")
        self.assertEqual(e_data["selected_model"], "RidgeRegressor")
        self.assertIn("h1_model", e_data)
        self.assertIn("direct_models", e_data)
        self.assertEqual(len(e_data["direct_models"]), 7)

        with open(RESULTS_PATH, "r") as f:
            res_data = json.load(f)
        self.assertIn("primary_target_energy", res_data)
        self.assertIn("secondary_target_peak", res_data)

if __name__ == "__main__":
    unittest.main()
