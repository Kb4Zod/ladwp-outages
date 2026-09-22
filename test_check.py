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
            {"id": 2, "customers": 50, "status": "REPORTED OUTAGE", "etr": None, "etr_text": None},
        ]

        html = check.render_page(state)

        self.assertIn("2 outages in Playa Del Rey", html)
        self.assertIn("150 customers affected", html)
        self.assertIn("CREWS WORKING", html)
        self.assertIn("REPORTED OUTAGE", html)

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

    def test_fetch_outages_ids_by_centroid_not_objectid(self):
        body = json.dumps(
            {
                "features": [
                    {
                        "attributes": {
                            "OBJECTID": 251108,
                            "COUNT_IN_RANK": 5,
                            "FAC_JOB_STATUS_NAM": "CREWS WORKING",
                            "ETR_DATETIME": None,
                            "ETR_DATETIME_CHAR": None,
                            "CENTROID_LAT": 33.95881,
                            "CENTROID_LNG": -118.44322,
                        }
                    }
                ]
            }
        ).encode("utf-8")

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = body
        mock_response.__enter__.return_value = mock_response
        mock_response.__exit__.return_value = False

        with patch("check.urlopen", return_value=mock_response):
            outages = check.fetch_outages()

        self.assertEqual(outages[0]["id"], "33.9588,-118.4432")
        self.assertEqual(outages[0]["objectid"], 251108)

    def test_outage_id_falls_back_to_objectid_when_centroid_missing(self):
        self.assertEqual(
            check._outage_id({"OBJECTID": 42, "CENTROID_LAT": None, "CENTROID_LNG": None}),
            42,
        )

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


class StatusChipTests(unittest.TestCase):
    def test_reported_outage_is_red(self):
        css_class, _, text = check._status_chip("REPORTED OUTAGE")
        self.assertEqual(css_class, "red")
        self.assertEqual(text, "REPORTED OUTAGE")

    def test_assigned_prefix_is_blue(self):
        css_class, _, _ = check._status_chip("ASSIGNED - IN QUEUE FOR DISPATCH")
        self.assertEqual(css_class, "blue")

    def test_crews_en_route_is_yellow(self):
        css_class, _, _ = check._status_chip("CREWS EN ROUTE")
        self.assertEqual(css_class, "yellow")

    def test_crews_working_is_purple(self):
        css_class, _, _ = check._status_chip("CREWS WORKING")
        self.assertEqual(css_class, "purple")

    def test_matching_is_case_insensitive(self):
        css_class, _, _ = check._status_chip("assigned - in queue")
        self.assertEqual(css_class, "blue")

    def test_unknown_status_is_grey(self):
        css_class, _, text = check._status_chip("SOMETHING ELSE")
        self.assertEqual(css_class, "grey")
        self.assertEqual(text, "Unknown status")

    def test_missing_status_is_grey(self):
        css_class, _, text = check._status_chip(None)
        self.assertEqual(css_class, "grey")
        self.assertEqual(text, "Unknown status")

    def test_render_page_shows_chip_class_for_each_status(self):
        state = base_state()
        state["outages"] = [
            {"id": 1, "customers": 1, "status": "REPORTED OUTAGE", "etr": None, "etr_text": None},
            {"id": 2, "customers": 1, "status": "ASSIGNED - IN QUEUE", "etr": None, "etr_text": None},
            {"id": 3, "customers": 1, "status": "CREWS EN ROUTE", "etr": None, "etr_text": None},
            {"id": 4, "customers": 1, "status": "CREWS WORKING", "etr": None, "etr_text": None},
            {"id": 5, "customers": 1, "status": "GIBBERISH", "etr": None, "etr_text": None},
        ]

        html = check.render_page(state)

        self.assertIn('chip-red', html)
        self.assertIn('chip-blue', html)
        self.assertIn('chip-yellow', html)
        self.assertIn('chip-purple', html)
        self.assertIn('chip-grey', html)
        self.assertIn('Unknown status', html)

    def test_legend_lists_five_chips_with_tooltips(self):
        html = check.render_page(base_state())

        self.assertIn('class="legend"', html)
        self.assertIn('title="An outage has been reported in your area"', html)
        self.assertIn('title="Repair crew has been assigned and is in queue to be dispatched"', html)
        self.assertIn('title="Repair crew is on the way"', html)
        self.assertIn('title="Repair crew is on-site working to restore power"', html)
        self.assertIn('title="Repair is complete"', html)


class RestoredOutageTests(unittest.TestCase):
    def test_outage_missing_from_successful_check_is_restored(self):
        previous = base_state()
        previous["outages"] = [
            {"id": 1, "customers": 42, "status": "CREWS WORKING", "etr": None, "etr_text": None}
        ]

        state = check.run_check(previous, fetch_fn=lambda: [], now=fixed_now())

        self.assertEqual(state["outages"], [])
        self.assertEqual(len(state["recently_restored"]), 1)
        restored = state["recently_restored"][0]
        self.assertEqual(restored["id"], 1)
        self.assertEqual(restored["customers"], 42)
        self.assertEqual(restored["status"], "CREWS WORKING")
        self.assertEqual(restored["restored_at"], fixed_now().isoformat())

    def test_same_centroid_different_objectid_is_not_restored(self):
        previous = base_state()
        previous["outages"] = [
            {"id": "33.9588,-118.4432", "objectid": 251089, "customers": 42, "status": "CREWS WORKING", "etr": None, "etr_text": None}
        ]

        state = check.run_check(
            previous,
            fetch_fn=lambda: [
                {"id": "33.9588,-118.4432", "objectid": 251108, "customers": 42, "status": "CREWS WORKING", "etr": None, "etr_text": None}
            ],
            now=fixed_now(),
        )

        self.assertEqual(state["recently_restored"], [])

    def test_missing_centroid_outage_falling_back_to_objectid_still_restores(self):
        previous = base_state()
        previous["outages"] = [
            {"id": 42, "objectid": 42, "customers": 7, "status": "REPORTED OUTAGE", "etr": None, "etr_text": None}
        ]

        state = check.run_check(previous, fetch_fn=lambda: [], now=fixed_now())

        self.assertEqual(len(state["recently_restored"]), 1)
        self.assertEqual(state["recently_restored"][0]["id"], 42)

    def test_outage_still_present_is_not_restored(self):
        previous = base_state()
        previous["outages"] = [
            {"id": 1, "customers": 42, "status": "CREWS WORKING", "etr": None, "etr_text": None}
        ]

        state = check.run_check(
            previous,
            fetch_fn=lambda: [
                {"id": 1, "customers": 42, "status": "CREWS WORKING", "etr": None, "etr_text": None}
            ],
            now=fixed_now(),
        )

        self.assertEqual(state["recently_restored"], [])

    def test_stale_check_leaves_recently_restored_untouched(self):
        previous = base_state()
        previous["recently_restored"] = [
            {"id": 1, "customers": 42, "status": "CREWS WORKING", "restored_at": fixed_now().isoformat()}
        ]

        def fetch():
            raise RuntimeError("boom")

        state = check.run_check(previous, fetch_fn=fetch, now=fixed_now())

        self.assertTrue(state["stale"])
        self.assertEqual(state["recently_restored"], previous["recently_restored"])

    def test_restored_entry_expires_after_24_hours_in_run_check(self):
        previous = base_state()
        previous["recently_restored"] = [
            {
                "id": 1,
                "customers": 42,
                "status": "CREWS WORKING",
                "restored_at": (fixed_now() - timedelta(hours=25)).isoformat(),
            }
        ]

        state = check.run_check(previous, fetch_fn=lambda: [], now=fixed_now())

        self.assertEqual(state["recently_restored"], [])

    def test_restored_entry_kept_under_24_hours_in_run_check(self):
        previous = base_state()
        previous["recently_restored"] = [
            {
                "id": 1,
                "customers": 42,
                "status": "CREWS WORKING",
                "restored_at": (fixed_now() - timedelta(hours=23)).isoformat(),
            }
        ]

        state = check.run_check(previous, fetch_fn=lambda: [], now=fixed_now())

        self.assertEqual(len(state["recently_restored"]), 1)

    def test_render_page_shows_restored_row_as_repair_complete(self):
        state = base_state()
        state["recently_restored"] = [
            {
                "id": 1,
                "customers": 42,
                "status": "CREWS WORKING",
                "restored_at": (fixed_now() - timedelta(hours=1)).isoformat(),
            }
        ]

        html = check.render_page(state, now=fixed_now())

        self.assertIn("Repair complete", html)
        self.assertIn("chip-green", html)
        self.assertIn("42 customers", html)
        self.assertIn("restored ", html)

    def test_render_page_hides_restored_row_after_24_hours(self):
        state = base_state()
        state["recently_restored"] = [
            {
                "id": 1,
                "customers": 42,
                "status": "CREWS WORKING",
                "restored_at": (fixed_now() - timedelta(hours=25)).isoformat(),
            }
        ]

        html = check.render_page(state, now=fixed_now())

        self.assertNotIn('class="outage restored"', html)
        self.assertNotIn("42 customers", html)

    def test_banner_totals_exclude_restored_outages(self):
        state = base_state()
        state["outages"] = [
            {"id": 2, "customers": 10, "status": "CREWS WORKING", "etr": None, "etr_text": None}
        ]
        state["recently_restored"] = [
            {
                "id": 1,
                "customers": 999,
                "status": "CREWS WORKING",
                "restored_at": (fixed_now() - timedelta(hours=1)).isoformat(),
            }
        ]

        html = check.render_page(state, now=fixed_now())

        self.assertIn("1 outage in Playa Del Rey", html)
        self.assertIn("10 customers affected", html)
        self.assertNotIn("999 customers affected", html)

    def test_banner_reads_no_outages_when_only_restored_remain(self):
        state = base_state()
        state["outages"] = []
        state["recently_restored"] = [
            {
                "id": 1,
                "customers": 999,
                "status": "CREWS WORKING",
                "restored_at": (fixed_now() - timedelta(hours=1)).isoformat(),
            }
        ]

        html = check.render_page(state, now=fixed_now())

        self.assertIn("No outages in Playa Del Rey", html)

    def test_old_state_without_recently_restored_key_still_renders(self):
        state = {
            "monitor_until": None,
            "last_check": None,
            "last_success": None,
            "stale": False,
            "outages": [],
        }

        html = check.render_page(state, now=fixed_now())

        self.assertIn("No outages in Playa Del Rey", html)

    def test_old_state_without_recently_restored_key_still_runs_check(self):
        state = {
            "monitor_until": None,
            "last_check": None,
            "last_success": None,
            "stale": False,
            "outages": [{"id": 1, "customers": 5, "status": "REPORTED OUTAGE", "etr": None, "etr_text": None}],
        }

        result = check.run_check(state, fetch_fn=lambda: [], now=fixed_now())

        self.assertEqual(len(result["recently_restored"]), 1)


if __name__ == "__main__":
    unittest.main()
