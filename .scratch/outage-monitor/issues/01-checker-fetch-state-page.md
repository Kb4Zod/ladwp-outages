# 01: Checker — fetch, state file, rendered page

**What to build:** A single stdlib-only Python script that, when run, queries LADWP's ArcGIS outage layer for exactly `CITY_NAM = 'PLAYA DEL REY'`, writes the state file, and renders a mobile-first static HTML page showing a banner (no outages / N outages, M customers), the last-check time, and one row per active outage (customers affected, LADWP status, estimated restore time in America/Los_Angeles). A failed fetch (non-200, non-JSON, missing fields) keeps the previous outage list, sets the stale flag, and the page shows a clear "data may be stale — last successful check <time>" warning. No monitoring-window logic in this ticket: every run checks. See `../spec.md` for the data source, field mapping, and state schema.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] Running the script with no arguments fetches live data and writes the state file and page; both are committed as repo files (page at repo root as `index.html`, state as `state.json`)
- [ ] State file matches the spec schema (`monitor_until` present but unused, `last_check`, `last_success`, `stale`, `outages[]` with id/customers/status/etr/etr_text)
- [ ] Page banner reads clearly for zero outages and for N outages with total customers; each outage row shows customers, status, and ETR (local time, or "unknown" when absent)
- [ ] On fetch failure: previous outages preserved, `stale: true`, `last_check` updated, `last_success` unchanged, page shows the stale warning; script exits 0
- [ ] The fetch is injectable so tests never hit the network; `python3 -m unittest` covers: outages present, empty result, HTTP error, malformed JSON, stale-preservation
- [ ] Request is polite: single GET, `returnGeometry=false`, limited outFields, a descriptive User-Agent, 20s timeout
- [ ] Page is readable on a phone (single column, no horizontal scroll, ≥16px text); inline CSS, no JS dependencies
- [ ] `.gitignore` for `__pycache__`; no third-party dependencies
