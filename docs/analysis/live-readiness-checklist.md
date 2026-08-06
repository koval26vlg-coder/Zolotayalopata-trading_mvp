# trading_mvp Live Readiness Checklist

Дата: 2026-06-17  
Статус: hard gate перед любым live-like этапом. Не является юридической, налоговой, финансовой или инвестиционной консультацией.

## 1. Gate Position

Live trading is blocked.

Переход к live нельзя делать автоматически даже если future research/postprocess примет setup. Максимальный следующий этап после accepted research — `paper-forward`, затем отдельный live-readiness review.

## 2. Required Pre-Live Evidence

| Gate | Required evidence | Status |
|---|---|---|
| Research setup accepted | final-review artifact with accepted rank/backtest/OOS/walk-forward/stress/sensitivity | Missing |
| Paper-forward accepted | frozen config, independent forward JSONL, positive net PnL after costs, enough trades, no hidden live execution | Missing |
| No overfit | OOS and walk-forward pass, not one-market/one-window artifact | Missing |
| Cost realism | fees, slippage, spread, fill probability, funding, basis risk included | Partial |
| Kill-switch tested | deterministic stop on daily loss, drawdown, API errors, stale data, reconciliation mismatch | Missing |
| User approval | explicit approval for live mode after evidence review | Missing |

Current result: live remains blocked.

## 3. API Key And Account Controls

Required before live:

- Separate exchange subaccount dedicated to the bot.
- API key scoped to minimum permissions.
- No withdrawal permission on trading keys.
- IP allowlist where venue supports it.
- Encrypted local secret storage; no keys in logs, JSON artifacts, shell history or docs.
- Manual key rotation plan.
- Emergency key revoke procedure tested.
- Max notional per order and per venue enforced in code, not only in config.
- Dry-run and paper mode must remain available and default.

Reject live if:

- key has withdrawal permission;
- key is shared with manual trading;
- any log/artifact contains a secret;
- bot can place orders without explicit `live=true` style approval gate.

## 4. Execution And Risk Controls

Required controls:

- Daily max loss.
- Per-trade max loss.
- Max open positions.
- Max notional per symbol.
- Max venue exposure.
- Max exchange concentration.
- Min liquidity/spread/fill-probability gates.
- Stale data protection.
- Force-close or disable-on-error policy.
- Idempotent order client.
- Post-only enforcement if strategy assumes maker execution.
- Reconciliation after every order/fill/cancel.
- Alert on order reject, partial fill, cancel failure, stale mark/index/funding, websocket disconnect and REST error burst.

For perp/funding strategies:

- funding accrual model;
- mark/index price monitoring;
- liquidation distance estimate;
- margin mode explicitly configured;
- leverage default `1x` unless separately approved;
- no auto-borrow or cross-margin by default;
- forced-close stress test.

## 5. Venue And Custody Risk Card

For every exchange used:

| Field | Required answer |
|---|---|
| Legal entity / jurisdiction | Known and documented |
| Spot/perp availability | Pair-specific |
| Fee tier | Actual account tier, maker/taker |
| Withdrawal status | Confirmed before capital allocation |
| API reliability | Error rate and outage history from paper/collector logs |
| Market integrity risk | Spoofing/wash/low-liquidity risk notes |
| Custody exposure | Max capital allowed on venue |
| Stablecoin risk | Quote asset and withdrawal rails |
| Incident response | What to do if exchange freezes, delists, halts or widens spreads |

Capital rule:

- Keep research/paper capital separate from custody reserves.
- Do not keep more capital on venue than the strategy needs for its tested exposure.
- No single venue should be existential for the project.

## 6. Compliance, 115-ФЗ, P2P And Off-Ramp

Recent channel videos about 115-ФЗ, P2P, taxes and custody reinforce this gate.

Project rules:

- P2P/off-ramp is not part of `trading_mvp` alpha.
- Do not route bot proceeds through ad-hoc P2P workflows.
- Do not model P2P spreads as trading profit unless a separate legal/operational risk model exists.
- Keep transaction/export logs sufficient for accounting and tax review.
- Track fiat on/off-ramp path separately from exchange PnL.
- Any bank/off-ramp workflow requires separate review before use.

Evidence basis:

- Bank of Russia has publicly discussed supervisory attention to high-risk operations connected with cryptocurrency and crypto exchangers.
- Bank of Russia has separately warned citizens about risks of involvement in criminal schemes when settling with crypto exchangers and online casinos.
- FNS guidance treats income from sale of cryptocurrency/digital currency as declarable/tax-relevant income context.

## 7. Logging And Audit Trail

Required logs:

- strategy config hash;
- code version / git commit or working tree fingerprint;
- exchange, symbol, order id, client order id;
- signal timestamp and order timestamp;
- bid/ask/mark/index/funding at decision and execution;
- expected vs actual fee;
- expected vs actual slippage;
- order status transitions;
- balance snapshots;
- reconciliation result;
- kill-switch state;
- every manual override.

Retention:

- Store raw logs and summarized artifacts separately.
- Never log secrets.
- Keep enough data to replay and explain every order.

## 8. Monitoring

Minimum dashboard/monitor:

- live/PnL vs paper expected;
- open positions;
- venue exposure;
- market exposure;
- last data timestamp by venue;
- REST/WebSocket error rate;
- order reject rate;
- partial fill rate;
- stale data flag;
- realized/unrealized PnL;
- daily loss and drawdown;
- kill-switch status.

Alert conditions:

- stale market data;
- exchange API outage;
- error burst;
- order mismatch;
- position mismatch;
- fee/slippage above configured cap;
- funding flip against carry position;
- basis gap above stress threshold;
- drawdown or loss cap breach.

## 9. Paper-Forward Exit Criteria

Paper-forward can advance to live-readiness review only if:

- duration is at least the approved forward window;
- independent data, not reused train/OOS;
- net PnL positive after costs;
- expectancy positive;
- profit factor >= configured gate;
- drawdown within cap;
- enough trades;
- no single market/venue dominates result unless strategy is explicitly market-specific;
- all rejects/errors are explained;
- no hidden manual intervention.

If paper-forward fails, do not "tune live". Return to research.

## 10. Live Approval Checklist

Before enabling live:

- [ ] accepted research final-review exists;
- [ ] accepted paper-forward decision exists;
- [ ] API key permissions reviewed;
- [ ] no withdrawal permission;
- [ ] encrypted secret storage configured;
- [ ] kill-switch tested;
- [ ] reconciliation tested;
- [ ] monitoring active;
- [ ] venue risk card complete;
- [ ] custody exposure limit set;
- [ ] off-ramp/P2P excluded or separately approved;
- [ ] tax/accounting export path exists;
- [ ] rollback/disable procedure tested;
- [ ] user explicitly approves live mode.

## 11. Current Project Decision

For current `trading_mvp` state:

- live trading: blocked;
- paper-forward: blocked until accepted 7d/multi-day final-review;
- P2P/off-ramp: excluded from MVP execution;
- custody/venue/compliance: mandatory gate before any live-like step;
- next valid evidence step: visible 7d funding/basis collect, then guarded final-review.

## 12. Sources

- YouTube channel: `https://www.youtube.com/@AnufrievNikita/`
- Bank of Russia, high-risk operations and crypto exchangers context: `https://www.cbr.ru/press/event/?id=18459`
- Bank of Russia, crypto exchangers / online casino risk warning: `https://cbr.ru/press/event/?id=24706`
- FNS, declaration of income from cryptocurrency sale: `https://www.nalog.gov.ru/rn25/ifns/r25_03/info/16604994/`
- IOSCO crypto/digital asset recommendations: `https://www.iosco.org/library/pubdocs/pdf/IOSCOPD747.pdf`

