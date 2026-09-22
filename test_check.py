import json
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import check


def fixed_now():
    return datetime(2026, 9, 21, 12, 0, 0, tzinfo=timezone.utc)


def base_state():
    return dict(check.DEFAULT_STATE)


class RunCheckTests(unittest.TestCase):
    def test_outages_present(self):
        def fetch():
            return [
                {
                    "id": 1,
                    "customers": 2137,
                    "status": "CREWS WORKING",
                    "etr": "2026-09-22T03:30:00+00:00",
                    "etr_text": "09/21/2026 20:30",
                }
            ]

        state = check.run_check(base_state(), fetch_fn=fetch, now=fixed_now())

        self.assertEqual(state["outages"], fetch())
        self.assertFalse(state["stale"])
        self.assertEqual(state["last_success"], fixed_now().isoformat())
        self.assertEqual(state["last_check"], fixed_now().isoformat())

    def test_empty_result(self):
        def fetch():
            return []

        state = check.run_check(base_state(), fetch_fn=fetch, now=fixed_now())

        self.assertEqual(state["outages"], [])
        self.assertFalse(state["stale"])
        self.assertEqual(state["last_success"], fixed_now().isoformat())

    def test_http_error(self):
        def fetch():
            raise RuntimeError("unexpected HTTP status 500")

        previous = base_state()
        previous["outages"] = [{"id": 1, "customers": 5, "status": "REPORTED", "etr": None, "etr_text": None}]
        previous["last_success"] = "2026-09-21T10:00:00+00:00"

        state = check.run_check(previous, fetch_fn=fetch, now=fixed_now())

        self.assertTrue(state["stale"])
        self.assertEqual(state["outages"], previous["outages"])
        self.assertEqual(state["last_success"], "2026-09-21T10:00:00+00:00")
        self.assertEqual(state["last_check"], fixed_now().isoformat())

    def test_malformed_json(self):
        def fetch():
            json.loads("not json")

        state = check.run_check(base_state(), fetch_fn=fetch, now=fixed_now())

        self.assertTrue(state["stale"])
        self.assertEqual(state["outages"], [])

    def test_stale_preserves_previous_outages_and_last_success(self):
        def fetch():
            raise ValueError("missing fields")

        previous = base_state()
        previous["outages"] = [{"id": 9, "customers": 100, "status": "ASSIGNED", "etr": None, "etr_text": None}]
        previous["stale"] = False
        previous["last_success"] = "2026-09-20T00:00:00+00:00"
        previous["last_check"] = "2026-09-20T00:00:00+00:00"

        state = check.run_check(previous, fetch_fn=fetch, now=fixed_now())

        self.assertTrue(state["stale"])
        self.assertEqual(state["outages"], previous["outages"])
        self.assertEqual(state["last_success"], "2026-09-20T00:00:00+00:00")
        self.assertEqual(state["last_check"], fixed_now().isoformat())


class RenderPageTests(unittest.TestCase):
    def test_zero_outages_banner(self):
        state = base_state()
        state["last_check"] = fixed_now().isoformat()

        html = check.render_page(state)

        self.assertIn("No outages in Playa Del Rey", html)

    def test_n_outages_banner_with_totals(self):
        state = base_state()
        state["outages"] = [
            {"id": 1, "customers": 100, "status": "CREWS WORKING", "etr": None, "etr_text": None},
            {"id": 2, "customers": 50, "status": "REPORTED", "etr": None, "etr_text": None},
        ]

        html = check.render_page(state)

        self.assertIn("2 outages in Playa Del Rey", html)
        self.assertIn("150 customers affected", html)
        self.assertIn("CREWS WORKING", html)
        self.assertIn("REPORTED", html)

    def test_missing_etr_shows_unknown(self):
        state = base_state()
        state["outages"] = [{"id": 1, "customers": 10, "status": "REPORTED", "etr": None, "etr_text": None}]

        html = check.render_page(state)

        self.assertIn("ETR: unknown", html)

    def test_stale_warning_shown(self):
        state = base_state()
        state["stale"] = True
        state["last_success"] = "2026-09-20T08:00:00+00:00"

        html = check.render_page(state)

        self.assertIn("stale", html.lower())
        self.assertIn("last successful check", html.lower())


class FetchOutagesUnitTests(unittest.TestCase):
    def test_arcgis_error_body_treated_as_failure(self):
        error_body = json.dumps(
            {"error": {"code": 400, "message": "Invalid field", "details": []}}
        ).encode("utf-8")

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = error_body
        mock_response.__enter__.return_value = mock_response
        mock_response.__exit__.return_value = False

        with patch("check.urlopen", return_value=mock_response):
            with self.assertRaises(RuntimeError):
                check.fetch_outages()

    def test_epoch_ms_to_iso_none(self):
        self.assertIsNone(check._epoch_ms_to_iso(None))

    def test_epoch_ms_to_iso_converts(self):
        iso = check._epoch_ms_to_iso(1758509400000)
        self.assertTrue(iso.startswith("2025-09-21") or iso.startswith("2025-09-22"))


if __name__ == "__main__":
    unittest.main()
