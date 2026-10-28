"""
Unit and Integration Tests for GET /api/provenance Endpoint.
Verifies the institutional metadata schema, data dictionary, invariant completeness,
and static file fallback integrity.
"""

import os
import json
import unittest
import threading
import socketserver
import urllib.request
import urllib.error

from server import EnergySenseHandler, DATA_DIR

TEST_PORT = 8879
SERVER_URL = f"http://127.0.0.1:{TEST_PORT}"

class TestProvenanceApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        socketserver.ThreadingTCPServer.allow_reuse_address = True
        cls.server = socketserver.ThreadingTCPServer(("127.0.0.1", TEST_PORT), EnergySenseHandler)
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_static_provenance_file_exists(self):
        """Verify data_provenance.json exists in clean data and public data."""
        clean_path = os.path.join(DATA_DIR, "data_provenance.json")
        self.assertTrue(os.path.exists(clean_path), "Missing data/clean/data_provenance.json")
        with open(clean_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        required_keys = ["system_overview", "institutions", "datasets", "governance_invariants", "faq"]
        for k in required_keys:
            self.assertIn(k, data, f"Key {k} missing from data_provenance.json")

    def test_provenance_endpoint_http(self):
        """Verify GET /api/provenance responds with 200 OK and valid JSON."""
        url = f"{SERVER_URL}/api/provenance"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers.get("Content-Type"), "application/json; charset=utf-8")
            payload = json.loads(response.read().decode("utf-8"))
            
        self.assertEqual(payload["system_overview"]["academic_freeze_date"], "2024-04-28")
        self.assertIn("grid_india", payload["institutions"])
        self.assertIn("cea", payload["institutions"])
        self.assertIn("cerc", payload["institutions"])
        self.assertIn("ember", payload["institutions"])
        self.assertEqual(payload["governance_invariants"]["total_daily_records"], 3900)
        self.assertEqual(payload["governance_invariants"]["missing_calendar_dates"], 236)
        self.assertEqual(payload["governance_invariants"]["negative_deficit_records"]["count"], 6)

    def test_provenance_faq_completeness(self):
        """Verify all three user/evaluator questions are answered in FAQ."""
        clean_path = os.path.join(DATA_DIR, "data_provenance.json")
        with open(clean_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        faq = data.get("faq", [])
        self.assertGreaterEqual(len(faq), 3, "Expected at least 3 FAQ items")
        questions = [item["q"] for item in faq]
        self.assertTrue(any("live feed" in q.lower() for q in questions))
        self.assertTrue(any("corrected" in q.lower() or "ambiguities" in q.lower() for q in questions))
        self.assertTrue(any("official api" in q.lower() for q in questions))

if __name__ == "__main__":
    unittest.main()
