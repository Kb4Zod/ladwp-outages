import json
import unittest
from datetime import datetime, timedelta, timezone
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

    def test_etr_renders_in_la_local_time(self):
        state = base_state()
        etr_iso = check._etr_from_fields("09/21/2026 20:30", None)
        state["outages"] = [
            {"id": 1, "customers": 10, "status": "REPORTED", "etr": etr_iso, "etr_text": "09/21/2026 20:30"}
        ]

        html = check.render_page(state)

        self.assertIn("8:30 PM PDT", html)

    def test_stale_warning_shown(self):
        state = base_state()
        state["stale"] = True
        state["last_success"] = "2026-09-20T08:00:00+00:00"

        html = check.render_page(state)

        self.assertIn("stale", html.lower())
        self.assertIn("last successful check", html.lower())


class FreshnessIndicatorTests(unittest.TestCase):
    def test_last_check_data_attribute_and_relative_text_seconds(self):
        state = base_state()
        state["monitor_until"] = (fixed_now() + timedelta(days=1)).isoformat()
        last_check = fixed_now() - timedelta(seconds=30)
        state["last_check"] = last_check.isoformat()

        html = check.render_page(state, now=fixed_now())

        self.assertIn(f'data-last-check="{last_check.isoformat()}"', html)
        self.assertIn(">30 seconds ago<", html)
        self.assertIn("Last checked:", html)

    def test_relative_text_minutes(self):
        state = base_state()
        state["monitor_until"] = (fixed_now() + timedelta(days=1)).isoformat()
        state["last_check"] = (fixed_now() - timedelta(minutes=5)).isoformat()

        html = check.render_page(state, now=fixed_now())

        self.assertIn(">5 minutes ago<", html)

    def test_relative_text_hours(self):
        state = base_state()
        state["monitor_until"] = (fixed_now() + timedelta(days=1)).isoformat()
        state["last_check"] = (fixed_now() - timedelta(hours=2)).isoformat()

        html = check.render_page(state, now=fixed_now())

        self.assertIn(">2 hours ago<", html)

    def test_badge_green_under_20_minutes(self):
        state = base_state()
        state["monitor_until"] = (fixed_now() + timedelta(days=1)).isoformat()
        state["last_check"] = (fixed_now() - timedelta(minutes=5)).isoformat()

        html = check.render_page(state, now=fixed_now())

        self.assertIn('data-freshness="green"', html)

    def test_badge_amber_between_20_and_60_minutes(self):
        state = base_state()
        state["monitor_until"] = (fixed_now() + timedelta(days=1)).isoformat()
        state["last_check"] = (fixed_now() - timedelta(minutes=45)).isoformat()

        html = check.render_page(state, now=fixed_now())

        self.assertIn('data-freshness="amber"', html)

    def test_badge_red_over_60_minutes(self):
        state = base_state()
        state["monitor_until"] = (fixed_now() + timedelta(days=1)).isoformat()
        state["last_check"] = (fixed_now() - timedelta(minutes=90)).isoformat()

        html = check.render_page(state, now=fixed_now())

        self.assertIn('data-freshness="red"', html)

    def test_badge_red_when_stale_even_if_recent(self):
        state = base_state()
        state["monitor_until"] = (fixed_now() + timedelta(days=1)).isoformat()
        state["last_check"] = (fixed_now() - timedelta(minutes=1)).isoformat()
        state["stale"] = True

        html = check.render_page(state, now=fixed_now())

        self.assertIn('data-freshness="red"', html)

    def test_badge_grey_and_not_monitoring_when_monitor_until_null(self):
        state = base_state()
        state["last_check"] = (fixed_now() - timedelta(minutes=1)).isoformat()

        html = check.render_page(state, now=fixed_now())

        self.assertIn('data-freshness="grey"', html)
        self.assertIn("not monitoring", html.lower())


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

    def test_etr_from_fields_none(self):
        self.assertIsNone(check._etr_from_fields(None, None))

    def test_etr_from_fields_prefers_char_over_epoch(self):
        # epoch here would decode (as UTC) to a different wall-clock time;
        # the char field must win.
        iso = check._etr_from_fields("09/21/2026 20:30", 1758529800000)
        dt = datetime.fromisoformat(iso)
        self.assertEqual((dt.hour, dt.minute), (20, 30))

    def test_etr_from_fields_falls_back_to_epoch_as_la_wall_clock(self):
        # 2026-09-21T20:30:00 UTC epoch ms, reinterpreted as LA wall-clock.
        epoch_ms = int(datetime(2026, 9, 21, 20, 30, tzinfo=timezone.utc).timestamp() * 1000)
        iso = check._etr_from_fields(None, epoch_ms)
        dt = datetime.fromisoformat(iso)
        self.assertEqual((dt.hour, dt.minute), (20, 30))
        self.assertEqual(dt.utcoffset(), check.LOS_ANGELES.utcoffset(datetime(2026, 9, 21, 20, 30)))


class MonitoringWindowTests(unittest.TestCase):
    def test_active_window(self):
        state = base_state()
        state["monitor_until"] = (fixed_now() + timedelta(days=1)).isoformat()

        self.assertTrue(check.is_monitoring_active(state, fixed_now()))
        self.assertFalse(check.is_monitoring_expired(state, fixed_now()))

    def test_null_window(self):
        state = base_state()

        self.assertFalse(check.is_monitoring_active(state, fixed_now()))
        self.assertFalse(check.is_monitoring_expired(state, fixed_now()))

    def test_expired_window(self):
        state = base_state()
        state["monitor_until"] = (fixed_now() - timedelta(days=1)).isoformat()

        self.assertFalse(check.is_monitoring_active(state, fixed_now()))
        self.assertTrue(check.is_monitoring_expired(state, fixed_now()))


class MainCliTests(unittest.TestCase):
    def setUp(self):
        patcher_open = patch("builtins.open", MagicMock())
        self.mock_open = patcher_open.start()
        self.addCleanup(patcher_open.stop)

        patcher_json_dump = patch("json.dump")
        self.mock_json_dump = patcher_json_dump.start()
        self.addCleanup(patcher_json_dump.stop)

        patcher_now = patch("check.datetime")
        self.mock_datetime = patcher_now.start()
        self.addCleanup(patcher_now.stop)
        self.mock_datetime.now.return_value = fixed_now()
        self.mock_datetime.fromisoformat.side_effect = datetime.fromisoformat
        self.mock_datetime.side_effect = lambda *a, **kw: datetime(*a, **kw)

    def test_start_sets_monitor_until_and_runs_check(self):
        with patch("check.load_state", return_value=base_state()):
            with patch("check.run_check") as mock_run_check:
                mock_run_check.side_effect = lambda state, now=None: state
                with patch("check.render_page", return_value="<html></html>"):
                    check.main(["--start", "3"])

        called_state = mock_run_check.call_args[0][0]
        self.assertEqual(
            called_state["monitor_until"],
            (fixed_now() + timedelta(days=3)).isoformat(),
        )

    def test_start_defaults_to_seven_days(self):
        with patch("check.load_state", return_value=base_state()):
            with patch("check.run_check") as mock_run_check:
                mock_run_check.side_effect = lambda state, now=None: state
                with patch("check.render_page", return_value="<html></html>"):
                    check.main(["--start"])

        called_state = mock_run_check.call_args[0][0]
        self.assertEqual(
            called_state["monitor_until"],
            (fixed_now() + timedelta(days=7)).isoformat(),
        )

    def test_stop_clears_monitor_until_without_fetching(self):
        state = base_state()
        state["monitor_until"] = (fixed_now() + timedelta(days=2)).isoformat()

        with patch("check.load_state", return_value=state):
            with patch("check.run_check") as mock_run_check:
                with patch("check.render_page", return_value="<html></html>") as mock_render:
                    check.main(["--stop"])

        mock_run_check.assert_not_called()
        rendered_state = mock_render.call_args[0][0]
        self.assertIsNone(rendered_state["monitor_until"])

    def test_plain_run_fetches_when_window_active(self):
        state = base_state()
        state["monitor_until"] = (fixed_now() + timedelta(days=1)).isoformat()

        with patch("check.load_state", return_value=state):
            with patch("check.run_check") as mock_run_check:
                mock_run_check.side_effect = lambda state, now=None: state
                with patch("check.render_page", return_value="<html></html>"):
                    check.main([])

        mock_run_check.assert_called_once()

    def test_plain_run_skips_fetch_when_window_null(self):
        with patch("check.load_state", return_value=base_state()):
            with patch("check.run_check") as mock_run_check:
                with patch("check.render_page", return_value="<html></html>"):
                    check.main([])

        mock_run_check.assert_not_called()

    def test_plain_run_skips_fetch_when_window_expired(self):
        state = base_state()
        state["monitor_until"] = (fixed_now() - timedelta(days=1)).isoformat()
        state["outages"] = [{"id": 1, "customers": 5, "status": "REPORTED", "etr": None, "etr_text": None}]
        state["stale"] = False
        state["last_success"] = "2026-09-20T00:00:00+00:00"

        with patch("check.load_state", return_value=state):
            with patch("check.run_check") as mock_run_check:
                with patch("check.render_page", return_value="<html></html>") as mock_render:
                    check.main([])

        mock_run_check.assert_not_called()
        rendered_state = mock_render.call_args[0][0]
        self.assertEqual(rendered_state["outages"], state["outages"])
        self.assertFalse(rendered_state["stale"])
        self.assertEqual(rendered_state["last_success"], "2026-09-20T00:00:00+00:00")


class RenderPageMonitoringTests(unittest.TestCase):
    def test_active_window_shows_monitoring_until(self):
        state = base_state()
        until = fixed_now() + timedelta(days=2)
        state["monitor_until"] = until.isoformat()

        html = check.render_page(state, now=fixed_now())

        self.assertIn("Monitoring until", html)

    def test_null_window_shows_not_monitoring_without_expired_note(self):
        state = base_state()
        state["last_check"] = fixed_now().isoformat()

        html = check.render_page(state, now=fixed_now())

        self.assertIn("Not monitoring", html)
        self.assertNotIn("Monitoring window has expired", html)

    def test_expired_window_shows_expired_note(self):
        state = base_state()
        state["monitor_until"] = (fixed_now() - timedelta(days=1)).isoformat()
        state["last_check"] = fixed_now().isoformat()

        html = check.render_page(state, now=fixed_now())

        self.assertIn("Not monitoring", html)
        self.assertIn("Monitoring window has expired", html)

    def test_not_monitoring_greys_out_results(self):
        state = base_state()
        state["outages"] = [{"id": 1, "customers": 5, "status": "REPORTED", "etr": None, "etr_text": None}]

        html = check.render_page(state, now=fixed_now())

        self.assertIn("greyed", html)


if __name__ == "__main__":
    unittest.main()
