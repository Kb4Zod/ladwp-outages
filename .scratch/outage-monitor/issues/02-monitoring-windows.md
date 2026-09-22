# 02: Monitoring windows — start, stop, expiry

**What to build:** The checker honours a monitoring window. `--start N` sets `monitor_until` to now + N days (UTC) and immediately runs a check; `--stop` clears it. A plain run fetches only while `monitor_until` is in the future; otherwise it skips the fetch and re-renders the page in a "not monitoring" state that still shows the last known result greyed out. The page shows "Monitoring until <local date/time>" while active, and "Not monitoring — last check <time>" otherwise, with a note when a window has expired. See `../spec.md`.

**Blocked by:** 01

**Status:** done (branch feat/monitor-windows)

- [ ] `--start N` (integer days, default 7) sets `monitor_until`, runs a check, writes state and page
- [ ] `--stop` sets `monitor_until` to null, re-renders without fetching
- [ ] Plain run with an active window fetches as in ticket 01
- [ ] Plain run with null or past `monitor_until` does not call the fetch, keeps outages/stale/last_success unchanged, and renders the "not monitoring" page (greyed last result, expired note when applicable)
- [ ] Page shows the monitoring status line in both states, in America/Los_Angeles
- [ ] Tests cover active / null / expired windows, `--start` and `--stop`, and that no fetch happens outside a window; `python3 -m unittest` passes
- [ ] Ticket 01 behaviour and tests still pass
