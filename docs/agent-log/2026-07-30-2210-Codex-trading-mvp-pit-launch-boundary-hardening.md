# PIT launch-boundary hardening

- Observed at: `2026-07-30T22:10:00+03:00`
- Scope: bounded offline code/tests only; no returns, PnL, OOS rows, network collector, replay, grid, retune, paper, or live execution.
- Finding: the countdown reauthorized the scheduled segment at window open, and the visible writer independently reauthorized it before mutating the run gate, but the countdown did not repeat its complete pointer/guard/disk/duplicate-owner preflight immediately before handing control to the writer.
- Fix:
  - rerun the complete runtime preflight after window-open segment authorization;
  - exit without a duplicate when another exact writer or countdown owner appears;
  - honor a fresh weekly-limit pause before launch;
  - require the exact segment to remain `DUE` and launchable after the repeated preflight;
  - retain the visible writer's independent stage authorization before any `RUNNING` gate mutation.
- Verification:
  - PowerShell parser check passed;
  - `57` focused policy tests passed;
  - `104` linked schedule, pointer, guard, postrun, train-target, and completion-audit tests passed;
  - exact `pit_universe_v2_forward_20260731_n03` `-PreflightOnly` returned `READY_NOT_DUE`, weekly remaining `56%`, no other countdown owners, and no run/output writes;
  - exact `-PlanOnly` returned `PLAN_VALIDATED` for schedule hash `31b4b6c73487953755409ce32dafb818c4bc8c61b7db67ecd709a6457ece8af7`;
  - no collector was launched.
- Next: preserve the immutable schedule. The preapproved `n03` segment remains eligible for one visible launch only when its exact window becomes due.
