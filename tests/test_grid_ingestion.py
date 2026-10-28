"""
Unit Tests for scripts/fetch_official_grid_data.py
Validates CLI operations, date sequencing, record schemas, validation rules,
and database extension table creation without corrupting canonical benchmark.
"""

import os
import sqlite3
import datetime
import unittest
import tempfile

from scripts.fetch_official_grid_data import (
    get_latest_database_date,
    generate_benchmark_extension_records,
    validate_records,
    append_to_sqlite,
    CANONICAL_FREEZE_DATE
)

class TestGridDataIngestion(unittest.TestCase):

    def test_canonical_freeze_date(self):
        """Verify canonical freeze date constant is 2024-04-28."""
        self.assertEqual(CANONICAL_FREEZE_DATE, datetime.date(2024, 4, 28))

    def test_database_latest_date_detection(self):
        """Verify get_latest_database_date returns 2024-04-28 from energysense.db."""
        latest_date = get_latest_database_date()
        self.assertEqual(latest_date, datetime.date(2024, 4, 28))

    def test_benchmark_extension_generation(self):
        """Verify 7-day benchmark generation generates valid, continuous daily series."""
        start = datetime.date(2024, 4, 29)
        end = datetime.date(2024, 5, 5)
        records = generate_benchmark_extension_records(start, end)
        
        self.assertEqual(len(records), 7)
        self.assertEqual(records[0]["date"], "2024-04-29")
        self.assertEqual(records[-1]["date"], "2024-05-05")
        
        for r in records:
            self.assertGreater(r["energy_met_mu"], 3000.0)
            self.assertGreater(r["peak_met_mw"], 150000.0)
            self.assertGreaterEqual(r["peak_unmet_mw"], 0.0)
            self.assertEqual(r["total_peak_demand_mw"], r["peak_met_mw"] + r["peak_unmet_mw"])
            self.assertEqual(r["is_negative_unmet"], 0)

    def test_record_validation_success_and_failure(self):
        """Verify record validation correctly identifies valid and invalid records."""
        valid_records = generate_benchmark_extension_records(
            datetime.date(2024, 4, 29),
            datetime.date(2024, 4, 30)
        )
        is_valid, errors = validate_records(valid_records)
        self.assertTrue(is_valid)
        self.assertEqual(len(errors), 0)
        
        # Test duplicate date rejection
        invalid_records = valid_records + [valid_records[0]]
        is_valid, errors = validate_records(invalid_records)
        self.assertFalse(is_valid)
        self.assertTrue(any("Duplicate date" in e for e in errors))
        
        # Test non-positive energy rejection
        bad_energy = [dict(valid_records[0])]
        bad_energy[0]["energy_met_mu"] = -50.0
        is_valid, errors = validate_records(bad_energy)
        self.assertFalse(is_valid)
        self.assertTrue(any("Non-positive" in e for e in errors))

    def test_isolated_db_extension_table(self):
        """Verify append_to_sqlite inserts into live_grid_extensions table."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp_db_path = tmp.name
            
        try:
            records = generate_benchmark_extension_records(
                datetime.date(2024, 4, 29),
                datetime.date(2024, 5, 2)
            )
            inserted = append_to_sqlite(records, db_path=tmp_db_path)
            self.assertEqual(inserted, 4)
            
            # Verify rows in sqlite
            conn = sqlite3.connect(tmp_db_path)
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM live_grid_extensions;")
            count = cur.fetchone()[0]
            conn.close()
            self.assertEqual(count, 4)
        finally:
            if os.path.exists(tmp_db_path):
                os.remove(tmp_db_path)

if __name__ == "__main__":
    unittest.main()
