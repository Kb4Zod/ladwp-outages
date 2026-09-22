#!/usr/bin/env python3
"""Fetches LADWP outage data for Playa Del Rey, updates state.json, renders index.html.

A plain run only fetches while a monitoring window (`monitor_until`) is active;
otherwise it re-renders the last known state without hitting the network.
`--start N` opens a window N days out and checks immediately; `--stop` closes
it without fetching. Exits 0 in all handled cases; a failed fetch is recorded
as stale data, not raised as an error.
"""
import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ARCGIS_URL = (
    "https://services2.arcgis.com/v0bIBBLIiGigCimX/ArcGIS/rest/services/"
    "PowerOutages_Data/FeatureServer/0/query"
)
USER_AGENT = "ladwp-outages-monitor/1.0 (+https://github.com/Kb4Zod/ladwp-outages)"
FETCH_TIMEOUT = 20

REPO_URL = "https://github.com/Kb4Zod/ladwp-outages"
START_WORKFLOW_URL = f"{REPO_URL}/actions/workflows/start.yml"
STOP_WORKFLOW_URL = f"{REPO_URL}/actions/workflows/stop.yml"
LADWP_MAP_URL = "https://www.ladwp.com/outages/power-outage-map"

STATE_PATH = "state.json"
PAGE_PATH = "index.html"

LOS_ANGELES = ZoneInfo("America/Los_Angeles")

DEFAULT_STATE = {
    "monitor_until": None,
    "last_check": None,
    "last_success": None,
    "stale": False,
    "outages": [],
    "recently_restored": [],
}

RESTORED_RETENTION_HOURS = 24

# (status prefix, css colour class, description) — matched case-insensitively,
# in order, against the start of the LADWP status string.
STATUS_RULES = [
    ("REPORTED OUTAGE", "red", "An outage has been reported in your area"),
    ("ASSIGNED", "blue", "Repair crew has been assigned and is in queue to be dispatched"),
    ("CREWS EN ROUTE", "yellow", "Repair crew is on the way"),
    ("CREWS WORKING", "purple", "Repair crew is on-site working to restore power"),
]

UNKNOWN_STATUS_TEXT = "Unknown status"
RESTORED_STATUS_TEXT = "Repair complete"

LEGEND_ITEMS = [
    ("red", "Reported outage", "An outage has been reported in your area"),
    ("blue", "Assigned", "Repair crew has been assigned and is in queue to be dispatched"),
    ("yellow", "Crews en route", "Repair crew is on the way"),
    ("purple", "Crews working", "Repair crew is on-site working to restore power"),
    ("green", RESTORED_STATUS_TEXT, "Repair is complete"),
]


def _status_chip(status):
    """Matches a raw LADWP status string to (css class, description, display text).

    Matching is case-insensitive by prefix. Unmatched or missing statuses map
    to the grey "Unknown status" chip.
    """
    if status:
        upper = status.strip().upper()
        for prefix, css_class, description in STATUS_RULES:
            if upper.startswith(prefix):
                return css_class, description, status
    return "grey", UNKNOWN_STATUS_TEXT, UNKNOWN_STATUS_TEXT


def _etr_from_fields(etr_text, epoch_ms):
    """Derives the ETR as an America/Los_Angeles-aware ISO8601 string.

    LADWP stores the epoch's wall-clock components as LA local time, not UTC
    (e.g. epoch decodes to 20:30 UTC when the actual ETR is 20:30 LA time), so
    the epoch can't be trusted as true UTC. ETR_DATETIME_CHAR is the reliable
    LA wall-clock source and is preferred; the epoch (reinterpreted as LA wall
    clock) is only a fallback for when the char field is missing or malformed.
    """
    if etr_text:
        try:
            naive = datetime.strptime(etr_text, "%m/%d/%Y %H:%M")
            return naive.replace(tzinfo=LOS_ANGELES).isoformat()
        except ValueError:
            pass
    if epoch_ms is not None:
        naive = datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc).replace(tzinfo=None)
        return naive.replace(tzinfo=LOS_ANGELES).isoformat()
    return None


def fetch_outages(timeout=FETCH_TIMEOUT):
    """Queries the ArcGIS layer for Playa Del Rey outages.

    Returns a list of outage dicts matching the state schema's outage shape.
    Raises on any non-200 response, non-JSON body, or missing expected fields —
    callers treat any exception here as a failed check.
    """
    query = urlencode(
        {
            "where": "CITY_NAM = 'PLAYA DEL REY'",
            "outFields": "OBJECTID,COUNT_IN_RANK,FAC_JOB_STATUS_NAM,ETR_DATETIME,ETR_DATETIME_CHAR",
            "returnGeometry": "false",
            "f": "json",
        }
    )
    request = Request(f"{ARCGIS_URL}?{query}", headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"unexpected HTTP status {response.status}")
        body = response.read()

    data = json.loads(body)
    if "error" in data:
        raise RuntimeError(f"ArcGIS returned an error: {data['error']}")
    features = data["features"]

    outages = []
    for feature in features:
        attrs = feature["attributes"]
        outages.append(
            {
                "id": attrs["OBJECTID"],
                "customers": attrs["COUNT_IN_RANK"],
                "status": attrs["FAC_JOB_STATUS_NAM"],
                "etr": _etr_from_fields(attrs["ETR_DATETIME_CHAR"], attrs["ETR_DATETIME"]),
                "etr_text": attrs["ETR_DATETIME_CHAR"],
            }
        )
    return outages


def _prune_expired_restored(entries, now):
    kept = []
    for entry in entries:
        restored_at = datetime.fromisoformat(entry["restored_at"])
        age_hours = (now - restored_at).total_seconds() / 3600
        if age_hours < RESTORED_RETENTION_HOURS:
            kept.append(entry)
    return kept


def run_check(state, fetch_fn=fetch_outages, now=None):
    """Runs one check against `state`, returning the updated state.

    On success: outages are replaced, stale cleared, last_success and last_check
    updated. Outages present in the previous check but absent from this one move
    into `recently_restored` (pruned of entries older than 24h). On failure:
    outages, last_success, and recently_restored are all preserved, stale is set.
    """
    now = now or datetime.now(timezone.utc)
    now_iso = now.isoformat()

    try:
        outages = fetch_fn()
    except Exception:
        state["stale"] = True
        state["last_check"] = now_iso
        return state

    previous_outages = state.get("outages") or []
    new_ids = {o["id"] for o in outages}
    newly_restored = [
        {
            "id": o["id"],
            "customers": o.get("customers"),
            "status": o.get("status"),
            "restored_at": now_iso,
        }
        for o in previous_outages
        if o["id"] not in new_ids
    ]
    recently_restored = state.get("recently_restored") or []
    state["recently_restored"] = _prune_expired_restored(
        recently_restored + newly_restored, now
    )

    state["outages"] = outages
    state["stale"] = False
    state["last_success"] = now_iso
    state["last_check"] = now_iso
    return state


def monitor_until_dt(state):
    """Parses `monitor_until` into an aware datetime, or None if unset."""
    value = state.get("monitor_until")
    if not value:
        return None
    return datetime.fromisoformat(value)


def is_monitoring_active(state, now):
    until = monitor_until_dt(state)
    return until is not None and until > now


def is_monitoring_expired(state, now):
    until = monitor_until_dt(state)
    return until is not None and until <= now


def _format_dt(iso_value, default):
    if not iso_value:
        return default
    dt = datetime.fromisoformat(iso_value).astimezone(LOS_ANGELES)
    return dt.strftime("%-m/%-d/%Y %-I:%M %p %Z")


def _format_etr(etr_iso):
    return _format_dt(etr_iso, "unknown")


def _format_last_check(iso_value):
    return _format_dt(iso_value, "never")


def _format_time_only(iso_value):
    if not iso_value:
        return "unknown time"
    dt = datetime.fromisoformat(iso_value).astimezone(LOS_ANGELES)
    return dt.strftime("%-I:%M %p")


def _relative_time(iso_value, now):
    """Renders how long ago `iso_value` was, relative to `now`."""
    if not iso_value:
        return "never"
    dt = datetime.fromisoformat(iso_value)
    seconds = max((now - dt).total_seconds(), 0)

    if seconds < 60:
        n = int(seconds)
        unit = "second" if n == 1 else "seconds"
        return f"{n} {unit} ago"

    minutes = seconds / 60
    if minutes < 60:
        n = int(minutes)
        unit = "minute" if n == 1 else "minutes"
        return f"{n} {unit} ago"

    hours = minutes / 60
    n = int(hours)
    unit = "hour" if n == 1 else "hours"
    return f"{n} {unit} ago"


def _freshness_class(state, now):
    """Determines the freshness badge colour class for `state`."""
    if state.get("monitor_until") is None:
        return "grey"
    if state.get("stale"):
        return "red"

    last_check = state.get("last_check")
    if not last_check:
        return "red"

    dt = datetime.fromisoformat(last_check)
    age_minutes = (now - dt).total_seconds() / 60
    if age_minutes < 20:
        return "green"
    if age_minutes <= 60:
        return "amber"
    return "red"


def render_page(state, now=None):
    """Renders the mobile-first static HTML page for the given state."""
    now = now or datetime.now(timezone.utc)
    outages = state.get("outages") or []
    count = len(outages)
    total_customers = sum(o.get("customers") or 0 for o in outages)

    if count == 0:
        banner = "No outages in Playa Del Rey"
    else:
        plural = "outage" if count == 1 else "outages"
        banner = f"{count} {plural} in Playa Del Rey — {total_customers} customers affected"

    active = is_monitoring_active(state, now)
    expired = is_monitoring_expired(state, now)

    if active:
        until_str = _format_dt(state.get("monitor_until"), "unknown")
        monitor_line = f'<p class="monitoring">Monitoring until {until_str}</p>'
    else:
        last_check_str = _format_last_check(state.get("last_check"))
        monitor_line = f'<p class="monitoring not-monitoring">Not monitoring — last check {last_check_str}</p>'
        if expired:
            monitor_line += '<p class="expired-note">Monitoring window has expired</p>'

    result_class = "results" if active else "results greyed"

    stale_warning = ""
    if state.get("stale"):
        last_success = _format_last_check(state.get("last_success"))
        stale_warning = (
            '<p class="stale">Data may be stale — last successful check: '
            f"{last_success}</p>"
        )

    active_rows = []
    for o in outages:
        css_class, description, text = _status_chip(o.get("status"))
        active_rows.append(
            '<li class="outage">'
            f'<span class="status-chip chip-{css_class}" title="{description}">{text}</span>'
            f'<span class="customers">{o.get("customers", "unknown")} customers</span>'
            f'<span class="etr">ETR: {_format_etr(o.get("etr"))}</span>'
            "</li>"
        )

    restored = state.get("recently_restored") or []
    restored = _prune_expired_restored(restored, now)
    restored_rows = []
    for entry in restored:
        restored_time = _format_time_only(entry.get("restored_at"))
        restored_rows.append(
            '<li class="outage restored">'
            f'<span class="status-chip chip-green" title="Repair is complete">{RESTORED_STATUS_TEXT}</span>'
            f'<span class="customers">{entry.get("customers", "unknown")} customers</span>'
            f'<span class="restored-at">restored {restored_time}</span>'
            "</li>"
        )

    rows = "\n".join(active_rows + restored_rows)
    outage_list = f"<ul>\n{rows}\n</ul>" if rows else ""

    legend_chips = "".join(
        f'<span class="legend-chip chip-{css_class}" title="{description}">{label}</span>'
        for css_class, label, description in LEGEND_ITEMS
    )
    legend = f'<div class="legend">{legend_chips}</div>'

    last_check_iso = state.get("last_check") or ""
    last_check_abs = _format_last_check(state.get("last_check"))
    last_check_rel = _relative_time(state.get("last_check"), now)
    freshness_class = _freshness_class(state, now)
    badge_label = "not monitoring" if freshness_class == "grey" else ""
    badge = (
        f'<span class="badge badge-{freshness_class}" data-freshness="{freshness_class}">'
        f"{badge_label}</span>"
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Playa Del Rey Outages</title>
<style>
  body {{
    font-family: system-ui, sans-serif;
    max-width: 480px;
    margin: 0 auto;
    padding: 16px;
    font-size: 16px;
    line-height: 1.4;
  }}
  .banner {{
    font-size: 1.25rem;
    font-weight: bold;
    padding: 12px;
    border-radius: 8px;
    background: #eee;
  }}
  .stale {{
    color: #a00;
    font-weight: bold;
  }}
  .last-check {{
    color: #555;
  }}
  ul {{
    list-style: none;
    padding: 0;
  }}
  .outage {{
    border: 1px solid #ccc;
    border-radius: 8px;
    padding: 12px;
    margin: 8px 0;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }}
  .monitoring {{
    color: #333;
    font-weight: bold;
  }}
  .not-monitoring {{
    color: #777;
  }}
  .expired-note {{
    color: #a00;
  }}
  .results.greyed {{
    opacity: 0.5;
  }}
  footer {{
    margin-top: 16px;
    padding-top: 8px;
    border-top: 1px solid #ccc;
    font-size: 0.85rem;
  }}
  footer a {{
    margin-right: 12px;
  }}
  .badge {{
    display: inline-block;
    width: 10px;
    height: 10px;
    border-radius: 50%;
    margin-right: 6px;
    vertical-align: middle;
  }}
  .badge-green {{
    background: #2a2;
    width: auto;
    height: auto;
    border-radius: 999px;
  }}
  .badge-green:empty {{
    width: 10px;
    height: 10px;
  }}
  .badge-amber {{
    background: #d90;
  }}
  .badge-red {{
    background: #c33;
  }}
  .badge-grey {{
    background: #999;
    width: auto;
    height: auto;
    border-radius: 999px;
    padding: 0 6px;
    color: #fff;
    font-size: 0.75rem;
    font-weight: normal;
  }}
  .status-chip {{
    display: inline-block;
    align-self: flex-start;
    padding: 2px 8px;
    border-radius: 999px;
    font-size: 0.8rem;
    font-weight: bold;
    color: #fff;
  }}
  .chip-red {{ background: #a00; }}
  .chip-blue {{ background: #06c; }}
  .chip-yellow {{ background: #a70; }}
  .chip-purple {{ background: #609; }}
  .chip-green {{ background: #2a2; }}
  .chip-grey {{ background: #666; }}
  .legend {{
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin: 8px 0;
  }}
  .legend-chip {{
    display: inline-block;
    padding: 2px 8px;
    border-radius: 999px;
    font-size: 0.75rem;
    font-weight: bold;
    color: #fff;
  }}
</style>
</head>
<body>
  {monitor_line}
  <div class="{result_class}">
  <p class="banner">{banner}</p>
  {stale_warning}
  {outage_list}
  {legend}
  <p class="last-check" data-last-check="{last_check_iso}">
    {badge}Last checked: {last_check_abs} &middot; checked <span id="relative-time">{last_check_rel}</span>
  </p>
  </div>
  <footer>
    <a href="{START_WORKFLOW_URL}">Start</a>
    <a href="{STOP_WORKFLOW_URL}">Stop</a>
    <a href="{LADWP_MAP_URL}">LADWP outage map</a>
  </footer>
  <script>
  (function () {{
    var el = document.querySelector('[data-last-check]');
    var rel = document.getElementById('relative-time');
    if (!el || !rel) return;
    var iso = el.getAttribute('data-last-check');
    if (!iso) return;
    function render() {{
      var then = new Date(iso).getTime();
      if (isNaN(then)) return;
      var seconds = Math.max((Date.now() - then) / 1000, 0);
      var text;
      if (seconds < 60) {{
        var n = Math.floor(seconds);
        text = n + (n === 1 ? ' second ago' : ' seconds ago');
      }} else if (seconds < 3600) {{
        var n = Math.floor(seconds / 60);
        text = n + (n === 1 ? ' minute ago' : ' minutes ago');
      }} else {{
        var n = Math.floor(seconds / 3600);
        text = n + (n === 1 ? ' hour ago' : ' hours ago');
      }}
      rel.textContent = text;
    }}
    render();
    setInterval(render, 30000);
  }})();
  </script>
</body>
</html>
"""


def load_state(path=STATE_PATH):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return dict(DEFAULT_STATE)


def parse_args(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", nargs="?", const=7, type=int, default=None)
    parser.add_argument("--stop", action="store_true")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    now = datetime.now(timezone.utc)
    state = load_state()

    if args.start is not None:
        state["monitor_until"] = (now + timedelta(days=args.start)).isoformat()
        state = run_check(state, now=now)
    elif args.stop:
        state["monitor_until"] = None
    elif is_monitoring_active(state, now):
        state = run_check(state, now=now)

    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
        f.write("\n")

    with open(PAGE_PATH, "w", encoding="utf-8") as f:
        f.write(render_page(state, now=now))

    return 0


if __name__ == "__main__":
    sys.exit(main())
