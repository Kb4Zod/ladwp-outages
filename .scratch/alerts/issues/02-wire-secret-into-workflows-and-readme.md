# 02: Wire NTFY_TOPIC into workflows and document setup

**What to build:** The three GitHub Actions workflows pass the `NTFY_TOPIC` repository secret to the checker as an environment variable, so alerts fire from the scheduled runs. The README gains an "Alerts" section: install the ntfy app, choose a long random topic name, subscribe, and set the secret with `gh secret set NTFY_TOPIC`. Verified end-to-end after merge by triggering a Check run and receiving a phone notification (orchestrator/Hugh).

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] `check.yml`, `start.yml`, `stop.yml` set `env: NTFY_TOPIC: ${{ secrets.NTFY_TOPIC }}` on the checker step; nothing else in the workflows changes
- [ ] README "Alerts" section covers app install, topic choice (random, unguessable), subscribing, setting the secret, and what each of the four alerts means
- [ ] Secret name is never echoed in logs
- [ ] `python3 -m unittest` still passes
- [ ] Post-merge manual check: with the secret set, `--stop` from GitHub produces a "Monitoring ended" push (then Start again) — orchestrator/Hugh
