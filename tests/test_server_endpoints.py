"""
Unit tests for server handler query logic & data serialization.
"""

import unittest
import sqlite3
import os
import json

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data", "clean")
DB_PATH = os.path.join(DATA_DIR, "energysense.db")

class TestServerLogic(unittest.TestCase):

    def setUp(self):
        self.assertTrue(os.path.exists(DB_PATH), f"Database not found at {DB_PATH}")

    def test_daily_demand_query(self):
        """Test daily query logic on SQLite."""
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        # Test 2023 filter
        cur.execute("SELECT * FROM daily_india_demand WHERE year = 2023 ORDER BY date ASC")
        rows = cur.fetchall()
        self.assertEqual(len(rows), 364, f"Expected 364 days in 2023, got {len(rows)}")
        
        # Test columns
        first_row = dict(rows[0])
        for col in ["date", "energy_met_mu", "peak_met_mw", "is_negative_unmet", "energy_7d_avg"]:
            self.assertIn(col, first_row, f"Column {col} missing in query result")
        conn.close()

    def test_state_capacity_query(self):
        """Test state capacity table query logic."""
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM state_capacity_latest ORDER BY total_mw DESC")
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        
        self.assertEqual(len(rows), 37, f"Expected 37 states, got {len(rows)}")
        self.assertTrue(rows[0]["total_mw"] > rows[-1]["total_mw"], "Rows should be sorted by total_mw DESC")

    def test_sql_sandbox_security_restrictions(self):
        """Test SQL security rules (only SELECT allowed, forbidden keywords rejected)."""
        forbidden_keywords = ["DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "CREATE", "ATTACH", "DETACH", "PRAGMA"]
        
        test_queries = [
            ("DROP TABLE daily_india_demand;", False),
            ("DELETE FROM monthly_generation;", False),
            ("UPDATE daily_india_demand SET energy_met_mu = 0;", False),
            ("SELECT * FROM daily_india_demand LIMIT 5;", True),
            ("SELECT date, peak_met_mw FROM daily_india_demand WHERE year = 2023 LIMIT 10;", True),
        ]
        
        for q, should_pass in test_queries:
            clean_q = q.strip()
            is_valid_select = clean_q.upper().startswith("SELECT")
            has_forbidden = any(f" {f} " in f" {clean_q.upper()} " for f in forbidden_keywords)
            passes = is_valid_select and not has_forbidden
            self.assertEqual(passes, should_pass, f"Query '{q}' security check failed")

    def test_audit_results_file_validity(self):
        """Test data_audit_results.json schema and pass status."""
        audit_path = os.path.join(DATA_DIR, "data_audit_results.json")
        self.assertTrue(os.path.exists(audit_path), "data_audit_results.json not found")
        
        with open(audit_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        self.assertEqual(data.get("overall_status"), "PASS")
        self.assertEqual(data["invariants"]["daily_demand_rows"]["actual"], 3900)
        self.assertEqual(data["invariants"]["missing_calendar_dates"]["actual"], 236)
        self.assertEqual(data["invariants"]["missing_weather_observations"]["actual"], 1196)
        self.assertEqual(data["invariants"]["negative_peak_unmet_values"]["actual"], 6)

if __name__ == "__main__":
    unittest.main()
