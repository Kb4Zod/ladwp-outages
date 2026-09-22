# Spec: Outage alerts (feature 2)

Status: ready-for-agent (planning approved 2026-09-22; not yet dispatched)

## Problem Statement

The monitor page only helps if Hugh remembers to look at it. During an outage he wants to be told, on his phone over cellular, when LADWP first registers an outage in Playa Del Rey and when it's over — without polling the page.

## Solution

While a monitoring window is active, each 15-minute check compares the new result to the previous one and sends a short push notification via ntfy.sh on meaningful transitions: outage started, all clear, data gone stale, monitoring window ended. Silence therefore means "monitoring, no change".

## User Stories

1. As Hugh, I want a push notification when the first outage appears in Playa Del Rey, so that I know LADWP is aware and roughly how big it is.
2. As Hugh, I want a notification when the last outage clears, so that I know power is restored area-wide.
3. As Hugh, I want a notification if checks have been failing for an hour, so that silence never means "no outage".
4. As Hugh, I want a notification when the monitoring window ends, so that I can restart it if the situation continues.
5. As Hugh, I want each notification to be one line with count, customers, and earliest ETR, plus a tap-through to the page, so that I get the gist without opening anything.
6. As Hugh, I want "outage started" to be high priority and the others normal, so that the important one breaks through.
7. As Hugh, I want no notification on ordinary count/status/ETR changes, so that a long event doesn't spam me every 15 minutes.
8. As Hugh, I want the ntfy topic kept out of the public repo, so that strangers can't push to my phone.
9. As Hugh, I want the checker to work unchanged when no topic is configured (local runs), so that alerts are opt-in.
10. As Hugh, I want a failed notification send to be logged but never to fail the check or corrupt state, so that the page stays correct regardless.
11. As Hugh, I want to receive at most one notification per transition, even if runs overlap or a run is retried, so that I don't get duplicates.

## Implementation Decisions

- **Transition detection** happens inside the checker after a check, by comparing the previous state (loaded at the start of the run) with the new one. Events: `started` (previous outages empty → non-empty), `cleared` (non-empty → empty), `stale` (`last_success` older than 60 minutes and the previous run had not yet alerted for this stale episode), `window_ended` (previous `monitor_until` in the future/non-null, now past or cleared by `--stop`).
- **Dedup:** the state file records `alerts: {"stale_notified": bool, "last_event": "<name>@<iso>"}`. `stale_notified` resets on the next success. Overlapping runs are already serialised by the workflow concurrency group.
- **Delivery:** HTTP POST to `https://ntfy.sh/<topic>` using stdlib `urllib`, headers `Title`, `Priority` (`high` for started, `default` otherwise), `Click` (the Pages URL), `Tags` (emoji). Topic comes from the environment variable `NTFY_TOPIC`; absent → alerts silently disabled. The workflows pass it from a repository secret of the same name.
- **Message format:** `⚡ Playa Del Rey: N outage(s), M customers, earliest ETR h:mm PM` / `✅ Playa Del Rey: all clear` / `⚠️ Playa Del Rey: no data for 1h+ (last success h:mm PM)` / `⏹ Monitoring ended — restart if needed`.
- **Send failure** is caught, printed to the run log, and never raises; state is written regardless.
- **Window expiry:** a plain run that finds `monitor_until` in the past clears it to null (so expiry fires once) and emits `window_ended`; `--stop` emits it too.
- The README gains a "Alerts" section: install ntfy app, pick a random topic, `gh secret set NTFY_TOPIC`.

## Testing Decisions

- Same single seam as feature 1: the checker run with an injectable fetch, plus an injectable notifier. Tests capture the notifier's calls and assert on (event, title, priority) for: none→outages, outages→none, outages→outages (no alert), consecutive stale runs (one alert), stale then success (reset), window expiry (one alert, `monitor_until` nulled), `--stop` (alert), no `NTFY_TOPIC` (no calls, no error), notifier raising (state still written).
- No live ntfy call in tests. One manual end-to-end after publish: set the secret, trigger a Check run, confirm a phone notification.

## Out of Scope

- Per-outage status/ETR change alerts, digests, quiet hours.
- Channels other than ntfy.
- Alerting outside an active monitoring window (except the window-ended event itself).

## Further Notes

Decisions from the 2026-09-22 grill; all recommendations accepted. Feature 1 is live at https://kb4zod.github.io/ladwp-outages/.
