# Anufriev P0 Alpha Transcript Retry Runbook

Дата: 2026-06-17  
Статус: frozen by user scope, not launched. Этот runbook сохранен только как audit trail. Новый фокус: не брать новый контент канала и работать над edge/high-winrate proof в `trading_mvp`.

## 1. Purpose

Цель: повторить transcript/timedtext extraction только для P0 alpha-видео, которые важны для trading strategy analysis: market-maker/orderbook claims и liquidation/risk psychology.

Это не стратегический backtest и не торговый прогон. Но это сетевой процесс, который пишет artifacts, поэтому запуск должен быть видимым.

## 2. Excluded Scope

Не анализировать и не ставить в retry priority для текущей цели:

- P2P;
- уголовка/суды/блокировки;
- вывод крипты;
- хранение крипты/custody;
- покупка крипты без 115-ФЗ;
- похожий legal/off-ramp контент.

Старые строки сохранены только как audit trail: `exports/youtube-anufriev/anufriev_transcript_retry_excluded_user_scope_20260617.csv`.

## 3. Prepared Inputs

| Artifact | Rows | Purpose |
|---|---:|---|
| `exports/youtube-anufriev/anufriev_transcript_retry_queue_p0_alpha_current_20260617.csv` | 2 | P0 alpha videos already present in 2026-06-06 yt-dlp metadata JSONL |
| `exports/youtube-anufriev/anufriev_transcript_retry_priority_alpha_current_20260617.csv` | 203 | alpha-focused retry priority list after exclusion |
| `exports/youtube-anufriev/anufriev_trading_relevant_metadata_20260606.jsonl` | existing | Metadata input used by `tools/anufriev_transcript_retry.py` |

Current P0 alpha queue:

| Rank | Video ID | Title | Why |
|---:|---|---|---|
| 1 | `mcYMwpHCdVM` | Как СНГ трейдеры зарабатывают на манипуляциях маркетмейкеров | orderbook/market-maker claim; Нарэк Григорян |
| 2 | `-lrecTTpK4c` | Психология в трейдинге: Как стабильно зарабатывать и не ликвидироваться? | orderbook/risk/liquidation-adjacent process claim |

## 4. Visible Command

Channel transcript work is frozen. The wrapper intentionally exits unless an explicit override is passed after the user reopens channel transcript work.

Do not run this for the active edge-proof path. Historical command if scope is explicitly reopened:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\start_anufriev_p0_transcript_retry_visible.ps1 -OverrideChannelFreeze
```

Optional slower mode:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\start_anufriev_p0_transcript_retry_visible.ps1 -OverrideChannelFreeze -SleepSec 120
```

The wrapper runs in the foreground, prints paths, uses `--stop-on-rate-limit`, and writes a console log.

## 5. Expected Outputs

Timestamped files:

- `exports/youtube-anufriev/anufriev_transcript_retry_p0_alpha_visible_<stamp>.jsonl`
- `exports/youtube-anufriev/anufriev_transcript_retry_p0_alpha_visible_<stamp>.state.json`
- `exports/trading-mvp/run/anufriev_transcript_retry_p0_alpha_visible_<stamp>.console.log`

## 6. Post-Run Review

After the visible run finishes:

1. Read the state summary.
2. Count `transcript_ok=true` rows in output JSONL.
3. If new claim cards exist, create/update a source packet.
4. Only then update participant/strategy/evidence scorecards.
5. If HTTP 429 occurs, stop and do not immediately retry.

## 7. Current Project Impact

No strategy verdict changes from preparing this runbook. `trading_mvp` still has `0` accepted trading strategies and live remains blocked. The next quantitative proof step remains visible 7d funding/basis collection only after explicit user confirmation.
