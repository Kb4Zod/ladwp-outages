# LADWP Playa Del Rey outage monitor

A tiny public page that shows whether LADWP has any active power outages in
Playa Del Rey right now: outage count, customers affected, status, and
estimated restore time per outage. It runs entirely on GitHub — Actions
checks LADWP's data every 15 minutes while a monitoring window is open, and
Pages serves the rendered page — so it keeps working even when the house is
offline.

## Start / stop monitoring

Monitoring runs for a fixed window (default 7 days) so checks only happen
when you actually care, e.g. during a storm.

**From the web:**
1. Go to the repo's **Actions** tab.
2. Pick **Start** (enter a number of days) or **Stop**, then **Run workflow**.

**From the GitHub mobile app:**
1. Open the repo, tap **Actions**.
2. Select **Start** or **Stop** in the workflow list.
3. Tap **Run workflow** (Start prompts for the number of days; use the
   default of 7 if unsure).

The page itself links to both workflow run pages in its footer, along with
LADWP's own outage map.

## Running locally

Requires only Python 3's standard library — no dependencies to install.

```sh
python3 check.py --start 7   # open a 7-day monitoring window and check now
python3 check.py             # run a single check if a window is active
python3 check.py --stop      # close the window
python3 -m unittest          # run the tests
```

Each run writes `state.json` (the source of truth) and re-renders
`index.html`.

## Data source caveat

Outage data comes from an internal LADWP ArcGIS layer behind their public
outage map, not a documented/published API. It could change or disappear
without notice. If a check fails (bad response, changed schema, LADWP
downtime), the page keeps showing the last known good result marked as
stale rather than a false "no outages".

## Pages configuration

GitHub Pages is configured to deploy from the `main` branch, root folder
(`/`). `.nojekyll` is present so Pages serves `index.html` as-is.
