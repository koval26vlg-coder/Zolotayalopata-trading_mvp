# Gate spot/perp basis convergence v2: terminal train closure

## Verdict

`INFEASIBLE_ON_CURRENT_DATA`

The frozen strategy is closed without OOS, grid search, threshold retuning, execution probe, paper-forward or live trading. The cost-derived entry threshold was not observed in the 100-day train window.

This verdict applies to the exact frozen contract `gate_spot_perp_basis_convergence_history_v2`. It does not claim that every possible Gate spot/perp strategy is impossible.

## Frozen Contract

| Field | Value |
|---|---:|
| Venue | Gate spot + Gate USDT linear perpetual |
| Direction | Long spot, short perpetual |
| Signal interval | 1 hour |
| Entry timing | Next trade-candle opens after a closed signal hour |
| Normal cycle cost | 82 bps |
| Stress cycle cost | 92 bps |
| Exit threshold | 20 bps |
| Safety margin | 20 bps |
| Frozen entry threshold | 132 bps |
| Maximum hold | 72 hours |
| Capital | $500 per leg, fully funded 1x |

The entry threshold was computed before train evaluation as `stress cost + exit threshold + safety margin`. It was not selected from returns.

## Data Pipeline

- Historical collector: `640/640` tasks, `0` errors, `0` missing archive files.
- Public network payload: `442,139,666` bytes.
- Collector runtime: `625.016086` seconds.
- Source mix: `560` Gate monthly archive files and `80` REST-tail requests.
- Data-quality survivors: `14/20`, above the frozen minimum of `8`.
- Accepted bases: `HYPE`, `PI`, `SKYAI`, `H`, `ESPORTS`, `UB`, `BLUAI`, `USELESS`, `XPIN`, `GRASS`, `VVV`, `AERO`, `BSV`, `SPX`.
- Train-only input: 20 warm-up days plus 100 train days. The 100-day OOS slice remained embargoed.

Gate documents its public historical archive formats in the official [Historical Data Download Update](https://www.gate.com/announcements/article/21688). Contract and funding fields are documented by the [Gate API v4 futures reference](https://www.gate.com/docs/developers/apiv4/en/futures/).

## Train Evidence

| Diagnostic | Result |
|---|---:|
| Train episodes | 0 |
| Entry dates | 0 |
| Assets with episodes | 0 |
| Maximum observed basis | 122.022080 bps |
| Aggregate p99 basis | 50.761421 bps |
| Hours at or above normal break-even, 102 bps | 10 |
| Hours at or above stress break-even, 112 bps | 6 |
| Hours at or above frozen entry, 132 bps | 0 |

The six observations above 112 bps were concentrated in two assets:

| Base | Maximum basis, bps | Hours >=102 | Hours >=112 | Hours >=132 |
|---|---:|---:|---:|---:|
| SKYAI | 122.022080 | 6 | 3 | 0 |
| ESPORTS | 119.958275 | 4 | 3 | 0 |
| BLUAI | 98.333333 | 0 | 0 | 0 |
| UB | 93.457944 | 0 | 0 | 0 |
| USELESS | 74.730141 | 0 | 0 | 0 |

The evaluator therefore did not have a qualifying signal to price. Funding did not block a valid entry, and gaps did not abort a position. Lowering the threshold would be a new, economically weaker hypothesis and is explicitly prohibited on this dataset.

## Rejection Gates

- `minimum_independent_episodes`
- `minimum_entry_dates`
- `minimum_assets_with_episodes`
- `price_normal_expectancy`
- `price_profit_factor`
- `positive_pnl_concentration`

The zero PnL values are not break-even performance. They mean no trade met the precommitted economic entry condition.

## Reproducibility

- Parent plan hash: `5377550919d3d77caea3e76d8af9d017ae84a63c05433c7899afd41c6eb139a2`.
- Quality artifact hash: `e753f25a6ce86667feae9606bceccd614ae2374e09f08db7933ad74a85146ac8`.
- Frozen train-plan hash: `6ac62370e46b7830d4daab084f19b4b4583e074490b91ccdef214da2ec14d40f`.
- Immutable train code-snapshot hash: `4a46b25c9262b167ea4cbb43509d03167f1158b614650ad88cd62ec265b9b62d`.
- Deterministic train result hash: `faa446e2e44d94f2135479ba793c15baa3a6d9e416b6fab221087d80f00e6c82`.
- Closure artifact hash: `a3cd42541c8134bd70043c1056f5b230a7b930eaf71ae1ab2ea408270a9866bd`.
- Closure manifest hash: `7cc52bc37f65023bf75408287ff34bff13ecc74bd0e410bcbcc403fa76cadc5a`.
- Independent closure read-back validation: `valid=true`.
- Focused test result: `22` active-gate/closure tests plus `11` strategy quality/train/closure tests passed.
- Full regression: `940` tests passed, `5` skipped, `0` failures/errors in `379.377` seconds.
- Windows reliability fix: nested PowerShell subprocesses now share UTF-8 output encoding; atomic probe-manifest replacement retries bounded transient file locks.

Machine artifacts:

- `E:\ZolotyayLopata-data\exports\trading-mvp\gate-spot-perp-v2\reports\gate_spot_perp_train_closure_20260717_fast_faa446e2e44d.closure.json`
- `E:\ZolotyayLopata-data\exports\trading-mvp\gate-spot-perp-v2\reports\gate_spot_perp_train_closure_20260717_fast_faa446e2e44d.closure.manifest.json`

## Next Allowed Work

This branch permits only one project-level transition: open a materially new PlanOnly hypothesis or continue the independent PIT shadow track. OOS, threshold retuning, grid, execution probes and trading are forbidden for this branch.
