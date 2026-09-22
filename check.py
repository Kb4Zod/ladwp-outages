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
}


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


def run_check(state, fetch_fn=fetch_outages, now=None):
    """Runs one check against `state`, returning the updated state.

    On success: outages are replaced, stale cleared, last_success and last_check
    updated. On failure: outages and last_success are preserved, stale is set.
    """
    now = now or datetime.now(timezone.utc)
    now_iso = now.isoformat()

    try:
        outages = fetch_fn()
    except Exception:
        state["stale"] = True
        state["last_check"] = now_iso
        return state

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

    if outages:
        rows = "\n".join(
            '<li class="outage">'
            f'<span class="customers">{o.get("customers", "unknown")} customers</span>'
            f'<span class="status">{o.get("status", "unknown")}</span>'
            f'<span class="etr">ETR: {_format_etr(o.get("etr"))}</span>'
            "</li>"
            for o in outages
        )
        outage_list = f"<ul>\n{rows}\n</ul>"
    else:
        outage_list = ""

    last_check = _format_last_check(state.get("last_check"))

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
</style>
</head>
<body>
  {monitor_line}
  <div class="{result_class}">
  <p class="banner">{banner}</p>
  {stale_warning}
  {outage_list}
  <p class="last-check">Last checked: {last_check}</p>
  </div>
  <footer>
    <a href="{START_WORKFLOW_URL}">Start</a>
    <a href="{STOP_WORKFLOW_URL}">Stop</a>
    <a href="{LADWP_MAP_URL}">LADWP outage map</a>
  </footer>
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
