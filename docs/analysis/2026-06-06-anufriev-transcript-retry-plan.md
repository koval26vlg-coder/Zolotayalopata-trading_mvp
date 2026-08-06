# Anufriev Transcript Retry Plan

Дата: 2026-06-06

Статус: continuation plan for transcript-level verification. Это не новый trading signal и не торговая рекомендация. Это слой доказательной проверки YouTube-первоисточников.

## 1. Зачем нужен retry

Текущий all-287 audit покрывает весь trading/crypto/investing-релевантный каталог на metadata-level, но transcript-level слой неполный:

| Метрика | Значение | Источник |
|---|---:|---|
| Trading-relevant видео | 287 | `exports/youtube-anufriev/anufriev_trading_relevant_scorecard_all287_20260606.csv` |
| Transcript-backed видео | 46 | `exports/youtube-anufriev/anufriev_trading_relevant_scorecard_all287_summary_20260606.json` |
| Metadata-only gaps | 241 | `exports/youtube-anufriev/anufriev_trading_relevant_scorecard_all287_summary_20260606.json` |
| ru auto-captions в metadata | 287 | `exports/youtube-anufriev/anufriev_trading_relevant_metadata_20260606.jsonl` |

Прямой transcript API остановился на IP block. Попытка через YouTube timedtext/json3 дала HTTP 429. Поэтому следующий корректный шаг: не усиливать выводы по metadata-only видео, а поставить их в приоритетную очередь повторной transcript-проверки.

## 2. Новые артефакты

| Artifact | Назначение |
|---|---|
| `exports/youtube-anufriev/anufriev_transcript_retry_queue_20260606.csv` | Очередь из 241 metadata-only видео, отсортированная по приоритету проверки |
| `exports/youtube-anufriev/anufriev_transcript_retry_queue_20260606_summary.json` | Формула ранжирования, counts by cluster, top 30 видео |
| `tools/anufriev_transcript_retry.py` | Resumable stdlib-only retry-tool для YouTube timedtext/json3 captions |
| `exports/youtube-anufriev/anufriev_transcript_retry_claim_cards_clean_20260606.jsonl` | Clean retry claim cards по top-31 priority videos после исправления theme regex |
| `exports/youtube-anufriev/anufriev_transcript_retry_claim_cards_20260606.jsonl` | Raw retry claim cards; сохранен для audit trail |
| `exports/youtube-anufriev/anufriev_transcript_retry_state_20260606.json` | State реального retry-запуска |
| `exports/youtube-anufriev/anufriev_transcript_retry_state_clean_20260606.json` | State clean reprocess запуска |
| `exports/youtube-anufriev/anufriev_transcript_retry_state_smoke_20260606.json` | Smoke state после проверки `--max-videos 0` |
| `exports/youtube-anufriev/anufriev_transcript_coverage_union_20260606.json` | Union coverage: базовые claim cards + timedtext attempt + retry cards |
| `exports/youtube-anufriev/anufriev_trading_relevant_scorecard_all287_with_retry_20260606.csv` | All-287 scorecard с обновленным evidence level для retry success |
| `docs/analysis/2026-06-06-anufriev-retry-batch-source-packet.md` | Video-level source packet по 31 clean retry cards |

## 3. Приоритизация

Очередь включает только строки, где `evidence_level == metadata`.

Формула:

```text
priority_score =
  sum(cluster_weights)
  + log10(view_count + 1) * 5
  + recent_2025_2026_boost
  + metadata_only_missing_transcript_boost
```

Cluster weights:

| Cluster | Weight | Причина |
|---|---:|---|
| `high_winrate_deposit_growth` | 40 | Самый рискованный claim family: win-rate, разгон, доходность |
| `orderbook_scalping` | 35 | Ближайший слой к `trading_mvp` и текущей стаканной стратегии |
| `futures_prop_moex` | 25 | Важен для pivot в derivatives/perp replay |
| `funding_passive_crypto` | 20 | Отдельная carry-модель и funding/basis модуль |
| `legal_regulatory_crypto` | 15 | Compliance/risk слой |
| `ai_trading` | 10 | Tooling/research claims требуют отделения от edge claims |
| `risk_psychology_playbook` | 10 | Операционные gates и playbook |
| `news_event_polymarket` | 10 | Возможный regime/catalyst filter |
| `general_trading` | 3 | Контекст, но ниже переносимость в код |
| `other_trading_adjacent` | 1 | Низкий приоритет, если нет конкретной стратегии |

Boosts:

| Component | Value |
|---|---:|
| Recent 2025-2026 | +5 |
| Metadata-only missing transcript | +20 |

Top 5 из очереди:

| Rank | Video | Cluster | Почему высоко |
|---:|---|---|---|
| 1 | `V-bu00UygbQ` - "Как заработать, когда рынок рушится? | Откровение маркетмейкера DWF Labs" | `orderbook_scalping,high_winrate_deposit_growth,ai_trading` | Пересекает market-maker/orderbook и high-winrate themes |
| 2 | `eUZcEUH_3Ak` - "Арбитраж криптовалюты P2P в 2022..." | `high_winrate_deposit_growth,risk_psychology_playbook,ai_trading,funding_passive_crypto` | High views + funding/arbitrage + доходность |
| 3 | `uHvHeSZG2vk` - "Как начать в трейдинге криптовалют со $100..." | `high_winrate_deposit_growth,risk_psychology_playbook,futures_prop_moex,general_trading` | Prop/futures + small capital/high-return framing |
| 4 | `mrPJmyUjKbM` - "Трейдинг криптовалют | Как в 21 год..." | `high_winrate_deposit_growth,ai_trading,futures_prop_moex,general_trading` | High-return + prop-trading |
| 5 | `6A9-0rrOUCw` - "Что такое опционы..." | `high_winrate_deposit_growth,ai_trading,futures_prop_moex,general_trading` | Derivatives/options + доходность framing |

## 4. Retry-tool

Tool:

```powershell
& 'C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe' tools\anufriev_transcript_retry.py `
  --queue exports\youtube-anufriev\anufriev_transcript_retry_queue_20260606.csv `
  --metadata exports\youtube-anufriev\anufriev_trading_relevant_metadata_20260606.jsonl `
  --output exports\youtube-anufriev\anufriev_transcript_retry_claim_cards_YYYYMMDD.jsonl `
  --state exports\youtube-anufriev\anufriev_transcript_retry_state_YYYYMMDD.json `
  --max-videos 20 `
  --sleep-sec 60 `
  --stop-on-rate-limit
```

Safety rules implemented:

| Rule | Реализация |
|---|---|
| Не сохранять полные транскрипты | Output пишет только `claim_windows` с короткими excerpts |
| Resume support | `--state` хранит attempts и last status |
| Не повторять уже успешные видео | Tool читает существующие `anufriev_transcript_claim_cards*.jsonl` и пропускает `transcript_ok=true` |
| Rate-limit awareness | HTTP 429 фиксируется; при `--stop-on-rate-limit` tool останавливается |
| No new dependency | Только Python stdlib: `urllib`, `csv`, `json`, `re` |
| Source grounding | Каждая claim card содержит `caption_source`, segment count, char count, matched themes |

Что tool пишет на успех:

```json
{
  "id": "...",
  "title": "...",
  "url": "...",
  "priority_rank": 1,
  "transcript_ok": true,
  "matched_themes": ["hft_orderbook_scalping"],
  "claim_windows": [{"start_sec": 12.3, "end_sec": 18.1, "themes": ["..."], "excerpt": "..."}],
  "caption_source": "automatic_captions:ru:json3",
  "transcript_segment_count": 1000,
  "transcript_char_count": 50000
}
```

## 5. Verification performed

Commands:

```powershell
& 'C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe' tools\anufriev_transcript_retry.py --help
```

```powershell
& 'C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe' tools\anufriev_transcript_retry.py `
  --queue exports\youtube-anufriev\anufriev_transcript_retry_queue_20260606.csv `
  --metadata exports\youtube-anufriev\anufriev_trading_relevant_metadata_20260606.jsonl `
  --output exports\youtube-anufriev\anufriev_transcript_retry_claim_cards_smoke_20260606.jsonl `
  --state exports\youtube-anufriev\anufriev_transcript_retry_state_smoke_20260606.json `
  --max-videos 0 `
  --sleep-sec 0 `
  --stop-on-rate-limit
```

Smoke result:

```json
{
  "processed": 0,
  "ok": 0,
  "failed": 0,
  "skipped_existing_success": 0,
  "skipped_state_success": 0,
  "stopped_on_rate_limit": false
}
```

Real retry batch:

```powershell
& 'C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe' tools\anufriev_transcript_retry.py `
  --queue exports\youtube-anufriev\anufriev_transcript_retry_queue_20260606.csv `
  --metadata exports\youtube-anufriev\anufriev_trading_relevant_metadata_20260606.jsonl `
  --output exports\youtube-anufriev\anufriev_transcript_retry_claim_cards_20260606.jsonl `
  --state exports\youtube-anufriev\anufriev_transcript_retry_state_20260606.json `
  --max-videos 10 `
  --sleep-sec 30 `
  --stop-on-rate-limit
```

Result:

```json
{
  "processed": 10,
  "ok": 10,
  "failed": 0,
  "skipped_existing_success": 1,
  "stopped_on_rate_limit": false
}
```

Clean reprocess after regex correction:

```powershell
& 'C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe' tools\anufriev_transcript_retry.py `
  --queue exports\youtube-anufriev\anufriev_transcript_retry_queue_20260606.csv `
  --metadata exports\youtube-anufriev\anufriev_trading_relevant_metadata_20260606.jsonl `
  --output exports\youtube-anufriev\anufriev_transcript_retry_claim_cards_clean_20260606.jsonl `
  --state exports\youtube-anufriev\anufriev_transcript_retry_state_clean_20260606.json `
  --max-videos 11 `
  --sleep-sec 15 `
  --stop-on-rate-limit `
  --reprocess
```

Result:

```json
{
  "processed": 11,
  "ok": 11,
  "failed": 0,
  "stopped_on_rate_limit": false
}
```

New transcript-backed videos:

| Video | Rank | Clean themes found | Evidence status |
|---|---:|---|---|
| `V-bu00UygbQ` | 1 | `hft_orderbook_scalping`, `market_maker_manipulation` | `metadata+transcript_retry_card` |
| `eUZcEUH_3Ak` | 2 | `crypto_regulation_legal`, `funding_basis_arbitrage`, `market_maker_manipulation` | `metadata+transcript_retry_card` |
| `uHvHeSZG2vk` | 3 | `crypto_regulation_legal`, `high_winrate_claims`, `news_event_trading`, `risk_psychology_process` | `metadata+transcript_retry_card` |
| `mrPJmyUjKbM` | 4 | `prop_moex_traditional`, `risk_psychology_process` | `metadata+transcript_retry_card` |
| `6A9-0rrOUCw` | 5 | `crypto_regulation_legal`, `funding_basis_arbitrage`, `high_winrate_claims`, `risk_psychology_process` | `metadata+transcript_retry_card` |
| `DLjlFGdx32M` | 6 | `crypto_regulation_legal`, `funding_basis_arbitrage`, `prop_moex_traditional` | `metadata+transcript_retry_card` |
| `54g-UwVL7Sc` | 7 | `crypto_regulation_legal`, `news_event_trading`, `risk_psychology_process` | `metadata+transcript_retry_card` |
| `JTM4z4bX8_I` | 8 | `crypto_regulation_legal`, `high_winrate_claims`, `market_maker_manipulation`, `news_event_trading` | `metadata+transcript_retry_card` |
| `tBh859wTAWg` | 9 | `crypto_regulation_legal`, `funding_basis_arbitrage`, `news_event_trading` | `metadata+transcript_retry_card` |
| `1kvXfO3uHdI` | 10 | `high_winrate_claims`, `risk_psychology_process` | `metadata+transcript_retry_card` |
| `RvHaM3SQHNE` | 11 | `funding_basis_arbitrage`, `hft_orderbook_scalping`, `high_winrate_claims`, `news_event_trading`, `prop_moex_traditional`, `risk_psychology_process` | `metadata+transcript_retry_card` |

Continuation batch after this clean reprocess added queue ranks 12-21 with the same safe settings (`--max-videos 10`, `--sleep-sec 30`, `--stop-on-rate-limit`) and finished with `processed=10`, `ok=10`, `failed=0`, `stopped_on_rate_limit=false`.

Union coverage after retry:

| Metric | Count |
|---|---:|
| Base transcript cards | 46 |
| timedtext attempt successes | 22 |
| Clean retry successes | 31 |
| Unique transcript-backed ids union | 77 |
| Remaining metadata-only rows in updated scorecard | 210 |

Synthetic JSON3 unit check:

| Check | Result |
|---|---|
| `_json3_segments` parses timedtext events | Passed |
| `_claim_windows` detects orderbook/market-maker/win-rate/risk themes | Passed |
| Excerpts are bounded and no full transcript is emitted | Passed |

## 6. How to use results

When new retry claim cards are collected:

1. Merge successful cards into the transcript-backed evidence set.
2. Update `anufriev_trading_relevant_scorecard_all287_20260606.csv` evidence level for successful videos.
3. Re-run strategy/participant audit for newly verified high-priority videos.
4. Update `docs/analysis/2026-06-06-anufriev-final-synthesis-v1.md` only where transcript evidence changes a conclusion.
5. Do not use metadata-only claims as proof of win-rate, profitability, or transferability into `trading_mvp`.

## 7. Current conclusion

This removes a process gap but does not close the full channel objective yet. The analysis is now better staged:

| Layer | Status |
|---|---|
| Full channel map | Complete at metadata level |
| Trading-relevant map | Complete at metadata level for 287 videos |
| Strategy decision package | Usable for engineering direction |
| Transcript-level verification | Incomplete; retry queue/tool created |
| Project action | Continue research-only `perp_replay` / sweep detector work, not live trading |
