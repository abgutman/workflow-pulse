"""
pulse.py — clock-true dispatcher for GitHub Actions workflows.

GitHub silently throttles `schedule:` triggers on this account to roughly 4-8
runs/day per repo, no matter how many cron lines a workflow declares (observed
Sept 2026: a 30-min cron delivering ~6/day, steady for weeks). Manual and API
`workflow_dispatch` triggers are NOT throttled. So this script runs as a
long-lived Actions job (self-chaining via a concurrency group: one running +
one queued) and POSTs workflow_dispatch to each target in targets.json on its
true interval.

Targets (targets.json):
    repo              — owner/name
    workflow          — workflow file name (e.g. ccp-typewatch.yml)
    interval_minutes  — dispatch cadence
    active_hours_et   — [start, end) hour in America/New_York; outside it the
                        target is skipped (the loop itself keeps running so the
                        chain survives the night and covers the next morning)

Env:
    PULSE_PAT     — token with actions:write on the target repos (required)
    LOOP_SECONDS  — loop lifetime; default 20700 (5h45m, under the 6h job cap)
    TICK_SECONDS  — poll granularity; default 60

Each target is dispatched once immediately on loop start (if in-window) — a
chain restart therefore never waits a full interval. Extra dispatches are safe:
every target gates on its own state file and concurrency group.
"""

import json
import logging
import os
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("pulse")

ET = ZoneInfo("America/New_York")
PAT = os.environ.get("PULSE_PAT", "")
LOOP_SECONDS = int(os.environ.get("LOOP_SECONDS", "20700"))
TICK_SECONDS = int(os.environ.get("TICK_SECONDS", "60"))
DRY_RUN = os.environ.get("DRY_RUN") == "1"


def dispatch(repo, workflow):
    url = f"https://api.github.com/repos/{repo}/actions/workflows/{workflow}/dispatches"
    req = urllib.request.Request(
        url,
        data=json.dumps({"ref": "main"}).encode(),
        headers={
            "Authorization": f"token {PAT}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "pulse-dispatcher",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status  # 204 on success
    except urllib.error.HTTPError as e:
        log.error("dispatch %s/%s -> HTTP %s: %s", repo, workflow, e.code,
                  e.read()[:200])
    except Exception as e:  # network blips must not kill the loop
        log.error("dispatch %s/%s -> %s", repo, workflow, e)
    return None


def main():
    if not PAT and not DRY_RUN:
        raise SystemExit("PULSE_PAT is not set")
    targets = json.loads(Path(__file__).with_name("targets.json").read_text())
    log.info("Pulse loop: %d target(s), lifetime %ds, tick %ds%s",
             len(targets), LOOP_SECONDS, TICK_SECONDS,
             " (DRY RUN)" if DRY_RUN else "")

    last = {}  # index -> monotonic time of last dispatch
    start = time.monotonic()

    while time.monotonic() - start < LOOP_SECONDS:
        now_et = datetime.now(ET)
        for i, t in enumerate(targets):
            lo, hi = t.get("active_hours_et", [0, 24])
            if not (lo <= now_et.hour < hi):
                continue
            if i in last and time.monotonic() - last[i] < t["interval_minutes"] * 60:
                continue
            if DRY_RUN:
                log.info("DRY RUN: would dispatch %s/%s", t["repo"], t["workflow"])
                last[i] = time.monotonic()
                continue
            status = dispatch(t["repo"], t["workflow"])
            if status == 204:
                last[i] = time.monotonic()
                log.info("dispatched %s/%s", t["repo"], t["workflow"])
            # On failure `last` is not advanced, so the next tick retries.
        time.sleep(TICK_SECONDS)

    log.info("Loop lifetime reached — exiting cleanly (queued successor takes over)")


if __name__ == "__main__":
    main()
