# pulse

Clock-true dispatcher for GitHub Actions workflows whose `schedule:` crons are
being throttled.

## The problem

GitHub silently drops most scheduled workflow runs on this account: roughly
4–8 delivered per repo per day, no matter how many cron lines the workflow
declares. Measured Sept 14–24, 2026 on `abgutman/barnett-alert` (a 30-minute
cron, ~30 expected/day): 5–8 actual runs every single day. The same holds for
`av-tools`, `gov-plaintiff-alert`, and `busy-biz`. GitHub status was green
throughout; this is throttling, not an outage. Manual and API
`workflow_dispatch` triggers are **not** throttled.

## The fix

A long-lived Actions job (`pulse.py`, ~5h45m per run) POSTs
`workflow_dispatch` to each target in `targets.json` on its true interval.
The workflow's concurrency group chains jobs — one running, one queued — so
GitHub only needs to deliver one cron fire every ~6 hours to keep the loop
alive. The dispatch cadence comes from the loop clock, not from cron.

- Targets keep their own (throttled) crons as a backstop; extra dispatches are
  harmless because every target gates on its own state file.
- Active windows are true `America/New_York` time (DST-correct, unlike raw
  UTC crons). Outside a target's window it is skipped but the loop keeps
  running, so the chain survives the night and covers the next morning.
- A daily heartbeat commit prevents GitHub's 60-day inactivity auto-disable
  of scheduled workflows.
- `DRY_RUN=1 LOOP_SECONDS=5 python3 pulse.py` exercises the loop locally
  without dispatching.

## Adding a target

Append to `targets.json`: `repo`, `workflow` (file name), `interval_minutes`,
`active_hours_et` `[start, end)`. The `PULSE_PAT` secret must have
`actions: write` on the target repo.

## Ops

- **Chain died?** (no runs listed) — trigger *Pulse dispatcher* manually via
  the Actions tab; the chain re-arms itself.
- **Secret:** `PULSE_PAT` — a GitHub PAT with `actions: write` on the target
  repos. Rotate here whenever the account PAT rotates.
- Dev copy of these files lives in `~/Desktop/claude_sandbox/pulse/`.
