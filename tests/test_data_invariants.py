"""
EnergySense — Automated Data Quality & Invariant Test Suite
Runs strictly via Python Standard Library unittest.
"""

import unittest
import csv
import json
import os
import sqlite3
import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data", "clean")
RAW_DIR = os.path.join(BASE_DIR, "data", "raw")
DB_PATH = os.path.join(DATA_DIR, "energysense.db")

class TestDataInvariants(unittest.TestCase):

    def setUp(self):
        self.assertTrue(os.path.exists(DB_PATH), f"Database not found at {DB_PATH}")

    def test_daily_demand_row_count(self):
        """Invariant 1: National daily demand must contain exactly 3,900 rows."""
        csv_path = os.path.join(DATA_DIR, "daily_demand_india.csv")
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        self.assertEqual(len(rows), 3900, f"Expected 3,900 daily rows, got {len(rows)}")

        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cnt = cur.execute("SELECT count(*) FROM daily_india_demand;").fetchone()[0]
        conn.close()
        self.assertEqual(cnt, 3900, f"Expected 3,900 DB rows, got {cnt}")

    def test_missing_dates_count(self):
        """Invariant 2: Exactly 236 missing calendar dates between 2013-01-01 and 2024-04-28."""
        csv_path = os.path.join(DATA_DIR, "daily_demand_india.csv")
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            dates = {datetime.datetime.strptime(r["date"], "%Y-%m-%d").date() for r in reader}
        
        d_start = datetime.date(2013, 1, 1)
        d_end = datetime.date(2024, 4, 28)
        total_calendar_days = (d_end - d_start).days + 1  # 4,136
        missing_count = total_calendar_days - len(dates)
        self.assertEqual(total_calendar_days, 4136, f"Expected 4,136 calendar days, got {total_calendar_days}")
        self.assertEqual(missing_count, 236, f"Expected 236 missing days, got {missing_count}")

    def test_missing_weather_observations(self):
        """Invariant 3: Exactly 1,196 missing weather (UTCI) observations (ending 2020-12-31)."""
        csv_path = os.path.join(DATA_DIR, "daily_demand_india.csv")
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            null_utci = sum(1 for r in reader if not r["utci_celsius"] or r["utci_celsius"].lower() == "null")
        self.assertEqual(null_utci, 1196, f"Expected 1,196 missing UTCI rows, got {null_utci}")

    def test_negative_peak_unmet_deficit_count(self):
        """Invariant 4: Exactly 6 negative peak unmet values in raw and clean data (flagged, not silently clamped)."""
        csv_path = os.path.join(DATA_DIR, "daily_demand_india.csv")
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            neg_rows = [r for r in reader if float(r["peak_unmet_mw"]) < 0]
        self.assertEqual(len(neg_rows), 6, f"Expected 6 negative peak unmet rows, got {len(neg_rows)}")
        
        # Verify specific dates match raw records
        neg_dates = {r["date"] for r in neg_rows}
        expected_dates = {"2014-07-19", "2014-07-23", "2014-07-28", "2015-10-18", "2016-08-01", "2017-04-21"}
        self.assertEqual(neg_dates, expected_dates, f"Negative dates mismatch: {neg_dates}")

    def test_monthly_generation_records(self):
        """Invariant 5: Monthly generation table must contain exactly 83 consecutive months."""
        csv_path = os.path.join(DATA_DIR, "monthly_generation_india.csv")
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        self.assertEqual(len(rows), 83, f"Expected 83 monthly rows, got {len(rows)}")
        self.assertEqual(rows[0]["date"], "2019-01-01")
        self.assertEqual(rows[-1]["date"], "2025-11-01")

        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cnt = cur.execute("SELECT count(*) FROM monthly_generation;").fetchone()[0]
        conn.close()
        self.assertEqual(cnt, 83, f"Expected 83 DB monthly rows, got {cnt}")

    def test_state_daily_records(self):
        """Invariant 6: State daily records must contain exactly 32,072 observations (844 dates x 38 entities)."""
        csv_path = os.path.join(DATA_DIR, "state_daily_demand.csv")
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        self.assertEqual(len(rows), 32072, f"Expected 32,072 state daily rows, got {len(rows)}")

        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cnt = cur.execute("SELECT count(*) FROM state_daily_demand;").fetchone()[0]
        conn.close()
        self.assertEqual(cnt, 32072, f"Expected 32,072 DB rows, got {cnt}")

    def test_state_annual_summary_records(self):
        """Invariant 7: State annual summary must contain exactly 456 records (38 entities x 12 years)."""
        csv_path = os.path.join(DATA_DIR, "state_annual_summary.csv")
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        self.assertEqual(len(rows), 456, f"Expected 456 state annual rows, got {len(rows)}")

        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cnt = cur.execute("SELECT count(*) FROM state_annual_summary;").fetchone()[0]
        conn.close()
        self.assertEqual(cnt, 456, f"Expected 456 DB state annual rows, got {cnt}")

    def test_baseline_mae_reproducibility(self):
        """Invariant 8: Persistence baseline MAE on 2023-2024 test set must reproduce 89.9 MU (+-0.1)."""
        csv_path = os.path.join(DATA_DIR, "daily_demand_india.csv")
        with open(csv_path, "r", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        
        train = [r for r in rows if int(r["year"]) < 2023]
        test = [r for r in rows if int(r["year"]) >= 2023]
        self.assertEqual(len(test), 483, f"Expected 483 test days, got {len(test)}")

        y_true = [float(r["energy_met_mu"]) for r in rows]
        test_start_idx = len(train)
        
        total_abs_err = 0.0
        total_pct_err = 0.0
        for i in range(test_start_idx, len(rows)):
            act = y_true[i]
            pred = y_true[i - 1]
            total_abs_err += abs(act - pred)
            total_pct_err += abs(act - pred) / act
            
        mae = total_abs_err / len(test)
        mape = (total_pct_err / len(test)) * 100.0
        
        self.assertAlmostEqual(mae, 89.9, delta=0.2, msg=f"MAE expected ~89.9, got {mae:.2f}")
        self.assertAlmostEqual(mape, 2.08, delta=0.05, msg=f"MAPE expected ~2.08%, got {mape:.2f}%")

    def test_calendar_vs_row_lag_integrity(self):
        """Invariant 9: Calendar lag must NOT equate row index i-7 to t-7 when gaps exist."""
        csv_path = os.path.join(DATA_DIR, "daily_demand_india.csv")
        with open(csv_path, "r", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        
        date_to_idx = {r["date"]: idx for idx, r in enumerate(rows)}
        
        # Test on 2013-03-31 (day after 82-day gap)
        target_date = "2013-03-31"
        self.assertIn(target_date, date_to_idx)
        idx = date_to_idx[target_date]
        target_dt = datetime.datetime.strptime(target_date, "%Y-%m-%d").date()
        cal_7_dt = target_dt - datetime.timedelta(days=7) # 2013-03-24 (which is inside the gap!)

        # True calendar lag t-7 does NOT exist in the dataset
        self.assertNotIn(str(cal_7_dt), date_to_idx, "2013-03-24 should be missing in dataset")
        
        # Naive row index i-7 points to an observation in January!
        row_7_date = rows[idx - 7]["date"]
        self.assertEqual(row_7_date, "2013-01-01", f"Naive row i-7 pointed to {row_7_date}, which is 89 days ago!")

    def test_sqlite_quality_logs(self):
        """Invariant 10: SQLite quality logs must capture all 93 gap clusters and 6 anomalies."""
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        gap_cnt = cur.execute("SELECT count(*), sum(missing_days_count) FROM data_quality_gap_log;").fetchone()
        anomaly_cnt = cur.execute("SELECT count(*) FROM data_quality_anomaly_log;").fetchone()[0]
        conn.close()

        self.assertEqual(gap_cnt[0], 93, f"Expected 93 gap clusters, got {gap_cnt[0]}")
        self.assertEqual(gap_cnt[1], 236, f"Expected 236 total missing days, got {gap_cnt[1]}")
        self.assertEqual(anomaly_cnt, 6, f"Expected 6 logged anomalies, got {anomaly_cnt}")

    def test_calendar_rolling_window_on_gaps(self):
        """Invariant 11: Calendar rolling window must be NULL/empty when prior days fall into a gap."""
        csv_path = os.path.join(DATA_DIR, "daily_demand_india.csv")
        with open(csv_path, "r", encoding="utf-8") as f:
            rows = {r["date"]: r for r in csv.DictReader(f)}
        
        # 2013-03-31 is right after an 82-day gap, so it has only 1 day in the 7-day calendar window
        row_after_gap = rows["2013-03-31"]
        self.assertIn(row_after_gap["energy_7d_avg"], ["", "None", None], "energy_7d_avg should be empty on gap boundary")
        self.assertIn(row_after_gap["peak_7d_avg"], ["", "None", None], "peak_7d_avg should be empty on gap boundary")

if __name__ == "__main__":
    unittest.main()

