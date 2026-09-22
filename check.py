#!/usr/bin/env python3
"""Fetches LADWP outage data for Playa Del Rey, updates state.json, renders index.html.

Every run checks (no monitoring-window logic yet). Exits 0 in all handled cases;
a failed fetch is recorded as stale data, not raised as an error.
"""
import json
import sys
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ARCGIS_URL = (
    "https://services2.arcgis.com/v0bIBBLIiGigCimX/ArcGIS/rest/services/"
    "PowerOutages_Data/FeatureServer/0/query"
)
USER_AGENT = "ladwp-outages-monitor/1.0 (+https://github.com/Kb4Zod/ladwp-outages)"
FETCH_TIMEOUT = 20

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


def _epoch_ms_to_iso(value):
    if value is None:
        return None
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()


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
                "etr": _epoch_ms_to_iso(attrs["ETR_DATETIME"]),
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


def _format_etr(etr_iso):
    if not etr_iso:
        return "unknown"
    dt = datetime.fromisoformat(etr_iso).astimezone(LOS_ANGELES)
    return dt.strftime("%-m/%-d/%Y %-I:%M %p %Z")


def _format_last_check(iso_value):
    if not iso_value:
        return "never"
    dt = datetime.fromisoformat(iso_value).astimezone(LOS_ANGELES)
    return dt.strftime("%-m/%-d/%Y %-I:%M %p %Z")


def render_page(state):
    """Renders the mobile-first static HTML page for the given state."""
    outages = state.get("outages") or []
    count = len(outages)
    total_customers = sum(o.get("customers") or 0 for o in outages)

    if count == 0:
        banner = "No outages in Playa Del Rey"
    else:
        plural = "outage" if count == 1 else "outages"
        banner = f"{count} {plural} in Playa Del Rey — {total_customers} customers affected"

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
</style>
</head>
<body>
  <p class="banner">{banner}</p>
  {stale_warning}
  {outage_list}
  <p class="last-check">Last checked: {last_check}</p>
</body>
</html>
"""


def load_state(path=STATE_PATH):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return dict(DEFAULT_STATE)


def main():
    state = load_state()
    state = run_check(state)

    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
        f.write("\n")

    with open(PAGE_PATH, "w", encoding="utf-8") as f:
        f.write(render_page(state))

    return 0


if __name__ == "__main__":
    sys.exit(main())
