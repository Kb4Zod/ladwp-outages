# Spec: Playa Del Rey outage monitor

Status: ready-for-agent

## Problem Statement

When the power goes out in Playa Del Rey, Hugh wants to know quickly whether LADWP knows about it, how many customers are affected, and when restoration is estimated — from his phone, with the house dark. LADWP's outage map is a heavy interactive ArcGIS app that is awkward to check repeatedly and impossible to glance at.

## Solution

A tiny public web page that, while a monitoring window is active, re-checks LADWP's outage data every 15 minutes and shows the current state of outages in Playa Del Rey: a clear banner (no outages / N outages, M customers) and a list of each active outage with status and estimated restore time. Hugh starts monitoring for a chosen number of days and can stop it early; the page runs entirely on GitHub (Actions cron + Pages), so it keeps working when his home is offline.

## User Stories

1. As Hugh, I want to start monitoring for N days with one action, so that the checks run only when I care (e.g. a storm week).
2. As Hugh, I want to stop monitoring early with one action, so that I'm not committed to the full window.
3. As Hugh, I want to see at a glance whether there are any outages in Playa Del Rey right now, so that I don't have to read details when the answer is "none".
4. As Hugh, I want each active outage listed with customers affected, LADWP status (reported / assigned / crews working), and estimated restore time, so that I know how serious it is and how long to expect.
5. As Hugh, I want the page to show when it last checked, so that I can judge how current the information is.
6. As Hugh, I want the page to show "monitoring until <date>" while a window is active, so that I know the checks are running.
7. As Hugh, I want a failed check (LADWP down, endpoint changed) to keep the last good result and mark it clearly as stale, so that I never see a false "no outages".
8. As Hugh, I want the page to say "not monitoring" outside a window while still showing the last known result greyed out, so that the page is never blank or misleading.
9. As Hugh, I want a link from the page to the start/stop actions, so that I can control it from my phone.
10. As Hugh, I want the page to work on a phone screen, so that it's usable during an outage.
11. As Hugh, I want only Playa Del Rey outages counted (not Playa Vista or neighbouring communities), so that the signal is exactly my neighbourhood.
12. As Hugh, I want the checker to be a plain Python script I can run locally, so that I can debug it without GitHub.
13. As Hugh, I want the check to be cheap and polite to LADWP's service, so that it isn't rate-limited or seen as abusive.
14. As Hugh, I want the repo's commit history to stay small, so that 15-minute runs don't bloat it.
15. As Hugh, I want to know when a monitoring window has expired, so that I can start another if needed.

## Implementation Decisions

- **Data source:** LADWP's public ArcGIS feature service behind their outage map (`PowerOutages_Data` layer, verified live 2026-09-21; no auth). Query with an exact `CITY_NAM = 'PLAYA DEL REY'` where-clause, `returnGeometry=false`, JSON output. Fields used per outage: customers affected (`COUNT_IN_RANK`), status (`FAC_JOB_STATUS_NAM`), estimated restore (`ETR_DATETIME` epoch ms and `ETR_DATETIME_CHAR`), object id. The endpoint is an internal LADWP AGOL layer, not a published product; treat any non-200, non-JSON, or schema-missing response as a failed check.
- **Checker:** one Python script, stdlib only (`urllib`, `json`, `datetime`). It reads the current state, decides whether a window is active, fetches if so, and writes the updated state and the rendered page. Exit code 0 in all handled cases so the cron never shows spurious failures; a failed fetch is data, not an error.
- **State file:** a single JSON document committed to the repo, the sole source of truth:
  ```json
  {
    "monitor_until": "2026-09-28T00:00:00Z" | null,
    "last_check": "<ISO8601>" | null,
    "last_success": "<ISO8601>" | null,
    "stale": false,
    "outages": [ { "id": 1, "customers": 2137, "status": "CREWS WORKING",
                   "etr": "<ISO8601>" | null, "etr_text": "09/21/2026 20:30" } ]
  }
  ```
  `outages` is replaced on a successful check and preserved on a failed one (with `stale: true`).
- **Window control:** two manually-triggered GitHub Actions workflows. *Start* takes an integer `days` input (default 7), sets `monitor_until = now + days`, runs one check immediately, commits. *Stop* sets `monitor_until = null`, re-renders, commits. A third *Check* workflow runs on a 15-minute cron and also on `workflow_dispatch`; if `monitor_until` is null or past, it re-renders (so the page flips to "not monitoring") without fetching.
- **Commits:** the workflow commits only if the state or page changed; otherwise nothing is pushed.
- **Page:** a single static HTML file rendered from the state by the checker, no JS framework, inline CSS, mobile-first. Sections: banner (state + count + total customers), monitoring status line (until-date or "not monitoring"), last-check line with stale warning when applicable, outage list, footer links to the Start and Stop workflow pages and to LADWP's map.
- **Hosting:** GitHub Pages serving from the repo (the rendered page lives at the Pages root). Public repo.
- **Time zones:** all stored timestamps UTC ISO8601; the page renders in America/Los_Angeles.

## Testing Decisions

- A good test exercises the checker's external behaviour — given a state file and a fetch result, what state and page come out — never its internals.
- **Single seam:** the checker's fetch function is injectable (or the endpoint URL is), so tests run the whole check with canned ArcGIS responses: active outages, empty result, HTTP error, malformed JSON. Assertions cover: window active/inactive/expired logic, outage list mapping, stale flag preserving previous outages, and the rendered page containing the expected banner text.
- Framework: stdlib `unittest`, run via `python3 -m unittest`, no dependencies. Prior art: the same approach in `rawnotes-triage`.
- Workflows are verified by running them once on GitHub after the repo is published (Start → page shows monitoring; Stop → page shows not monitoring).

## Out of Scope

- Push/email/SMS alerts on outage start or end (candidate feature 2).
- History/log of past outages.
- Any community other than Playa Del Rey, or zip-based filtering.
- An always-on server, buttons on the page itself, or authentication.
- Map rendering of outage locations.

## Further Notes

- At spec time there were 4 live outages in Playa Del Rey, so real data is available for manual testing immediately.
- If the AGOL layer disappears, the stale flag is the safety net; fallbacks (PowerOutage.us, @LADWP) are documented in the grill but not built.
