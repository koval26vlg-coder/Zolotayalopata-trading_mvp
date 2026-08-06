# PIT quality-ledger transaction hardening

- Observed at: `2026-07-30T22:12:00+03:00`
- Scope: bounded offline code and fixture tests only; no network collector, market replay, returns, PnL, OOS rows, grid, retune, paper, or live execution.
- Finding:
  - certification IDs and retry behavior already prevented logical duplicate entries;
  - the physical ledger commit still used an in-place append, so process or host failure could leave a truncated JSONL line;
  - the old exclusive-create lock file could survive a crashed writer and block a later valid retry before commit.
- Fix:
  - replace the existence-based lock with a persistent cross-process OS lock (`msvcrt` on Windows, `flock` elsewhere), which the operating system releases when a process exits;
  - under that lock, revalidate the exact prior certification sequence;
  - build `existing bytes + pending immutable entries` in a unique temp file, flush and `fsync`, then atomically replace the ledger;
  - remove only the transaction temp file on failure and preserve the last committed ledger unchanged.
- Verification:
  - a simulated `os.replace` failure preserved the original ledger byte-for-byte, removed the temp file, released the OS lock, and allowed a retry to append exactly one entry;
  - a concurrent second lock acquisition was rejected and the lock remained reusable after release;
  - `20` focused quality/postrun tests passed;
  - `106` linked schedule, pointer, guard, postrun, train-target, and completion-audit tests passed;
  - exact current `run_trading_mvp_pit_postrun.ps1 -PlanOnly` returned `PLAN_VALIDATED`, `4/20`, `mutation=false`, and left ledger SHA-256 `24f1b79f3b61c09b9532c70a023f256f3fbec3e5bfac3e21a3a01fc2692d5b4a` unchanged.
- Next: retain the immutable `n03` schedule. Its completed output can now move into the sealed quality ledger through a crash-safe, idempotent commit before the postrun branch advances.
