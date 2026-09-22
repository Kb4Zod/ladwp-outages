# 01: Transition alerts via ntfy

**What to build:** During a check, the checker detects transitions against the previous state — outage started, all clear, data stale for 1h+, monitoring window ended — and sends one short ntfy.sh push per transition (title, one-line body, priority high for "started", tap-through to the page). Alerts are enabled only when `NTFY_TOPIC` is set; a send failure is logged and never affects state or exit code. Dedup fields are stored in the state file. Expired windows are cleared to null so the ended-alert fires once. See `../spec.md` for events, message formats, and dedup rules.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] `started`, `cleared`, `stale` (≥60 min since `last_success`, once per episode), and `window_ended` (expiry or `--stop`) each produce exactly one notification; ordinary changes produce none
- [ ] Notification: POST to `https://ntfy.sh/$NTFY_TOPIC` with Title, Priority (high for started), Click = page URL, message per spec format
- [ ] No `NTFY_TOPIC` → no HTTP call, no error, checker behaves as today
- [ ] Notifier failure (exception/HTTP error) is printed and swallowed; state and page still written; exit 0
- [ ] State file gains `alerts` sub-object per spec; existing fields unchanged; an old state file without `alerts` still loads
- [ ] Plain run with a past `monitor_until` nulls it (so the page says "not monitoring" and the alert fires once)
- [ ] Notifier is injectable; unit tests cover all cases listed in the spec's Testing Decisions; `python3 -m unittest` passes; stdlib only
- [ ] Feature-1 tests still pass; page rendering unchanged
