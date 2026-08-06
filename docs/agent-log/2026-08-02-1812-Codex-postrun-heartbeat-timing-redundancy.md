# Postrun heartbeat timing redundancy

- Observed at: 2026-08-02 18:12 +03:00.
- Agent: Codex.
- Goal: prevent an avoidable idle stop between the exact dense writer finish and the frozen postrun deadline.
- Finding: the prior heartbeat schedule checked at 01:30 and then 01:55. If the writer changed the gate shortly after 01:30, the next check could leave only 35 minutes before the 02:30 hard deadline.
- Change: updated the existing `trading-continuous-production` heartbeat only. Added minute 35 to its daily 00:00-01:55 checkpoints.
- New RRULE: `FREQ=DAILY;BYHOUR=0,1;BYMINUTE=0,25,30,35,55`.
- Automation SHA-256: `904311b0e69a73165c32919cf7374f09f9e2f77b21cf14123d8a1799df235aa8`.
- The 01:35 checkpoint may launch postrun only after a clean exact PreflightOnly and a matching READY gate. It may not create a second owner or retry STOPPED_INCOMPLETE.
- No strategy, venue, universe, signal, cost, risk, collector, postrun runtime, output cap, PlanOnly, or approval hash changed.
- No collector, postrun, evaluator, returns/PnL/OOS, grid/retune, paper/live, private API, capital, leverage, or margin action was started.
- Final guard: `ACTIVE`, `WAIT_APPROVED_LONG_CAMPAIGN_WINDOW`, weekly remaining 65%, no critical notification.
