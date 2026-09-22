# 01: Relative "checked N minutes ago" freshness indicator

**What to build:** The page's last-checked line becomes obviously live: it shows the absolute time as today plus a relative phrase ("checked 3 minutes ago") that updates in the browser every 30 seconds without a reload, using the ISO timestamp embedded in the page. A small colour dot/badge reflects freshness: green under 20 minutes, amber 20–60 minutes, red over 60 minutes or when the stale flag is set. Outside a monitoring window the badge is grey and the text reads "not monitoring". No framework; a few lines of inline JS with a no-JS fallback to the absolute time.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] Last-checked line renders `data-last-check="<ISO8601>"` and shows "Last checked: <absolute local time> · checked N minutes ago" (seconds under 1 min, hours over 60)
- [ ] Relative text refreshes every 30 s client-side; page with JS disabled still shows the absolute time
- [ ] Freshness badge: green <20 min, amber 20–60 min, red >60 min or `stale: true`; grey with "not monitoring" when `monitor_until` is null
- [ ] Stale warning text from ticket 01 of outage-monitor is unchanged
- [ ] Rendering is tested at the existing seam: unit tests assert the data attribute and the badge class for fresh/amber/red/stale/not-monitoring states (JS behaviour not unit-tested)
- [ ] `python3 -m unittest` passes; stdlib only; mobile layout unchanged
