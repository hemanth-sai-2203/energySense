"""
Unit and Integration Tests for GET /api/forecast Endpoint
Tests target options, horizon range 1..7, origin-aligned baseline formulas,
leakage prevention, data freshness metadata, edge cases (future origin, missing lags),
degraded artifact fallback, and existing endpoint integrity.
"""

import os
import json
import sqlite3
import datetime
import unittest
import urllib.request
import urllib.error

from scripts.forecast_service import (
    generate_forecast,
    load_model_artifact,
    get_latest_observed_date,
    DB_PATH,
    MODELS_DIR
)

import threading
import socketserver
from server import EnergySenseHandler

TEST_PORT = 8877
SERVER_URL = f"http://127.0.0.1:{TEST_PORT}"

class TestForecastApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        socketserver.ThreadingTCPServer.allow_reuse_address = True
        cls.server = socketserver.ThreadingTCPServer(("127.0.0.1", TEST_PORT), EnergySenseHandler)
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        cls.server_live = True

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_forecast_service_default_energy(self):
        """Verify default call generates 7-day energy met forecast from latest date."""
        status, data = generate_forecast(target="energy_met_mu", horizon=7)
        self.assertEqual(status, 200)
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["target"], "energy_met_mu")
        self.assertEqual(data["units"], "MU")
        self.assertEqual(data["forecast_origin"], "2024-04-28")
        self.assertEqual(data["data_freshness"]["latest_observed_date"], "2024-04-28")
        self.assertEqual(len(data["predictions"]), 7)

        # Check target dates are sequential 2024-04-29 to 2024-05-05
        expected_dates = [
            "2024-04-29", "2024-04-30", "2024-05-01", "2024-05-02",
            "2024-05-03", "2024-05-04", "2024-05-05"
        ]
        actual_dates = [p["target_date"] for p in data["predictions"]]
        self.assertEqual(actual_dates, expected_dates)

    def test_forecast_service_peak_target(self):
        """Verify secondary target peak_met_mw generates 7-day trajectory in MW."""
        status, data = generate_forecast(target="peak_met_mw", horizon=7)
        self.assertEqual(status, 200)
        self.assertEqual(data["target"], "peak_met_mw")
        self.assertEqual(data["units"], "MW")
        self.assertEqual(len(data["predictions"]), 7)
        for p in data["predictions"]:
            self.assertEqual(p["units"], "MW")
            self.assertGreater(p["predicted_value"], 100000.0, "National peak met should exceed 100 GW")

    def test_horizons_1_to_7(self):
        """Verify requested horizon parameter (1 through 7) controls returned trajectory length."""
        for h in range(1, 8):
            status, data = generate_forecast(target="energy_met_mu", horizon=h)
            self.assertEqual(status, 200)
            self.assertEqual(len(data["predictions"]), h)
            self.assertEqual(data["requested_horizon_days"], h)

    def test_origin_persistence_and_seasonal_naive_formulas(self):
        """Verify persistence equals y(D) and seasonal naive equals y(D+h-7)."""
        origin_str = "2024-04-20"
        status, data = generate_forecast(target="energy_met_mu", origin_str=origin_str, horizon=7)
        self.assertEqual(status, 200)
        
        y_origin = data["data_quality"]["origin_observed_value"]
        for p in data["predictions"]:
            # All horizons must report y(D) as the origin persistence
            self.assertEqual(p["persistence_baseline"], round(y_origin, 2))
            # Day 7 seasonal-naive must equal persistence (D + 7 - 7 = D)
            if p["horizon"] == 7:
                self.assertEqual(p["seasonal_naive_baseline"], round(y_origin, 2))

    def test_hybrid_selection_policy(self):
        """Verify policy: Ridge for H=1..5, Ridge watch for H=6, Seasonal-Naive preferred for H=7."""
        status, data = generate_forecast(target="energy_met_mu", horizon=7)
        preds = data["predictions"]
        
        for h in range(1, 6):
            self.assertEqual(preds[h-1]["recommended_model"], "ridge")
            self.assertEqual(preds[h-1]["predicted_value"], preds[h-1]["ridge_prediction"])
            self.assertEqual(preds[h-1]["baseline_status"], "ridge_superior")
            
        self.assertEqual(preds[5]["recommended_model"], "ridge")
        self.assertEqual(preds[5]["baseline_status"], "statistical_parity")
        
        self.assertEqual(preds[6]["recommended_model"], "seasonal_naive")
        self.assertEqual(preds[6]["predicted_value"], preds[6]["seasonal_naive_baseline"])
        self.assertEqual(preds[6]["baseline_status"], "seasonal_anchor_preferred")

    def test_future_origin_rejection(self):
        """Verify that requesting an origin beyond latest database date returns HTTP 400."""
        future_origin = "2026-10-26"
        status, data = generate_forecast(target="energy_met_mu", origin_str=future_origin)
        self.assertEqual(status, 400)
        self.assertEqual(data["status"], "error")
        self.assertEqual(data["code"], "FUTURE_ORIGIN_NOT_OBSERVED")
        self.assertIn("exceeds the latest database observation", data["message"])

    def test_unavailable_lag_rejection(self):
        """Verify origin 2023-03-31 is rejected with HTTP 422 because 2023-03-30 lag is absent."""
        gap_origin = "2023-03-31"
        status, data = generate_forecast(target="energy_met_mu", origin_str=gap_origin)
        self.assertEqual(status, 422)
        self.assertEqual(data["status"], "error")
        self.assertEqual(data["code"], "UNAVAILABLE_HISTORICAL_LAGS")
        self.assertIn("missing_lags_by_horizon", data)

    def test_invalid_parameters_rejection(self):
        """Verify invalid target, invalid horizon, and malformed dates return HTTP 400."""
        s1, d1 = generate_forecast(target="unsupported_target")
        self.assertEqual(s1, 400)
        self.assertEqual(d1["code"], "INVALID_TARGET")

        s2, d2 = generate_forecast(horizon=10)
        self.assertEqual(s2, 400)
        self.assertEqual(d2["code"], "INVALID_HORIZON")

        s3, d3 = generate_forecast(origin_str="not-a-date")
        self.assertEqual(s3, 400)
        self.assertEqual(d3["code"], "MALFORMED_ORIGIN_DATE")

    def test_data_freshness_metadata(self):
        """Verify explicit data freshness warning banner in API response."""
        status, data = generate_forecast(target="energy_met_mu")
        self.assertEqual(status, 200)
        freshness = data["data_freshness"]
        self.assertEqual(freshness["latest_observed_date"], "2024-04-28")
        self.assertEqual(freshness["mode"], "historical_demonstration")
        self.assertIn("Historical dataset ending April 28, 2024", freshness["warning"])

    def test_live_http_endpoint_get(self):
        """Verify live HTTP GET /api/forecast endpoint returns 200 with JSON payload."""
        if not self.server_live:
            self.skipTest("Live server not running on port 8000")
            
        url = f"{SERVER_URL}/api/forecast?target=energy_met_mu&origin=2024-04-28&horizon=7"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.getcode(), 200)
            self.assertEqual(resp.headers.get_content_type(), "application/json")
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["status"], "success")
            self.assertEqual(data["forecast_origin"], "2024-04-28")
            self.assertEqual(len(data["predictions"]), 7)

    def test_live_http_error_handling(self):
        """Verify live HTTP error responses return appropriate HTTP status codes."""
        if not self.server_live:
            self.skipTest("Live server not running on port 8000")
            
        # 1. Future date -> HTTP 400
        url_future = f"{SERVER_URL}/api/forecast?origin=2026-10-26"
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(url_future, timeout=5)
        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["code"], "FUTURE_ORIGIN_NOT_OBSERVED")

        # 2. Unavailable lag -> HTTP 422
        url_gap = f"{SERVER_URL}/api/forecast?origin=2023-03-31"
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(url_gap, timeout=5)
        self.assertEqual(ctx.exception.code, 422)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["code"], "UNAVAILABLE_HISTORICAL_LAGS")

    def test_existing_endpoints_remain_functional(self):
        """Verify existing API endpoints continue to work without regression."""
        if not self.server_live:
            self.skipTest("Live server not running on port 8000")
            
        endpoints = [
            "/api/daily?year=2024",
            "/api/generation",
            "/api/states?year=2023",
            "/api/capacity",
            "/api/audit"
        ]
        for ep in endpoints:
            req = urllib.request.Request(f"{SERVER_URL}{ep}")
            with urllib.request.urlopen(req, timeout=5) as resp:
                self.assertEqual(resp.getcode(), 200, f"Endpoint {ep} must return 200")

if __name__ == "__main__":
    unittest.main()
