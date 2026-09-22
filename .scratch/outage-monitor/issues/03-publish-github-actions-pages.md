# 03: Publish — GitHub Actions workflows and Pages

**What to build:** Run the monitor on GitHub so it works when Hugh's home is offline. Three workflows: **Start** (manual, integer `days` input, default 7) runs `--start N`; **Stop** (manual) runs `--stop`; **Check** runs every 15 minutes and on manual trigger. Each commits `state.json` and `index.html` back to `main` only when they changed. GitHub Pages serves `index.html` from the repo root on `main`. The page footer links to the Start and Stop workflow pages and to LADWP's outage map. A short README explains how to start/stop from the GitHub mobile app. See `../spec.md`.

**Blocked by:** 02

**Status:** ready-for-agent

- [ ] Three workflow files as described; cron every 15 minutes; all three use only `python3` from the runner (no pip)
- [ ] Workflows commit and push only when `state.json`/`index.html` changed; concurrency guard so overlapping runs don't race
- [ ] Workflow permissions limited to `contents: write`
- [ ] Page footer links to the Start and Stop workflow pages (repo URL parameterised or documented) and to LADWP's outage map
- [ ] README: what it is, how to Start/Stop (web + mobile app), how to run locally, the data-source caveat
- [ ] Pages configuration documented (deploy from branch `main`, root); `.nojekyll` present
- [ ] `python3 -m unittest` still passes
- [ ] Verified after publish (orchestrator/Hugh): Start run → page shows monitoring + live outages; Stop run → page shows not monitoring
