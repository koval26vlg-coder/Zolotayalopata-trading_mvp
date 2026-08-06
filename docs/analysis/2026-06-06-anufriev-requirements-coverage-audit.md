# Requirements Coverage Audit: Anufriev Channel Goal

Дата: 2026-06-06  
Статус: audit of completion evidence. Цель не закрыта полностью из-за transcript/rate-limit gaps, но текущий пакет достаточен для инженерных решений по `trading_mvp`.

## 1. Objective decomposition

Исходная цель требует:

1. Изучить максимальное количество видео канала.
2. Выявить успешные стратегии и варианты высокого win-rate.
3. Сравнить стратегии между собой.
4. Сравнить участников.
5. Проверить claims через внешние источники.
6. Понять, что правда, а что маркетинговое искажение.
7. Сопоставить стратегии с текущим `trading_mvp`.
8. Определить корректировки проекта, включая возможный pivot.
9. Прикинуть экономические модели.
10. Собрать информацию воедино и предоставить выводы.

## 2. Evidence inventory

| Evidence | Path | Status |
|---|---|---|
| Full channel catalog | `exports/youtube-anufriev/anufriev_video_catalog_20260606.csv` | 461 videos |
| Trading-relevant catalog | `exports/youtube-anufriev/anufriev_trading_relevant_catalog_20260606.csv` | 287 videos |
| All-287 metadata dump | `exports/youtube-anufriev/anufriev_trading_relevant_metadata_20260606.jsonl` | 287 videos |
| All-287 scorecard | `exports/youtube-anufriev/anufriev_trading_relevant_scorecard_all287_20260606.csv` | Complete metadata-level map |
| All-287 summary | `exports/youtube-anufriev/anufriev_trading_relevant_scorecard_all287_summary_20260606.json` | 20 562 076 views |
| Transcript claim cards | `exports/youtube-anufriev/anufriev_transcript_claim_cards_20260606.jsonl` | 46 success / 241 failed |
| Timedtext attempt | `exports/youtube-anufriev/anufriev_transcript_claim_cards_ytdlp_all287_20260606.jsonl` | 22 success, then HTTP 429; pre-retry union still 46 |
| Transcript retry queue | `exports/youtube-anufriev/anufriev_transcript_retry_queue_20260606.csv` | 241 metadata-only videos prioritized |
| Transcript retry queue summary | `exports/youtube-anufriev/anufriev_transcript_retry_queue_20260606_summary.json` | Ranking formula, counts by cluster, top 30 |
| Transcript retry tool | `tools/anufriev_transcript_retry.py` | Resumable timedtext/json3 retry, short claim windows only |
| Transcript retry cards clean | `exports/youtube-anufriev/anufriev_transcript_retry_claim_cards_clean_20260606.jsonl` | 31 successes: top-priority queue videos |
| Transcript coverage union | `exports/youtube-anufriev/anufriev_transcript_coverage_union_20260606.json` | 77 unique transcript-backed ids |
| All-287 scorecard with retry | `exports/youtube-anufriev/anufriev_trading_relevant_scorecard_all287_with_retry_20260606.csv` | 46 base cards, 31 retry cards, 210 metadata-only |
| All-287 scorecard with retry summary | `exports/youtube-anufriev/anufriev_trading_relevant_scorecard_all287_with_retry_summary_20260606.json` | Updated cluster transcript-backed counts |
| Transcript retry plan | `docs/analysis/2026-06-06-anufriev-transcript-retry-plan.md` | Concrete continuation path for transcript gaps |
| Transcript retry source packet | `docs/analysis/2026-06-06-anufriev-retry-batch-source-packet.md` | Video-level source packet for 31 retry cards |
| Main audit | `docs/analysis/2026-06-06-anufriev-channel-strategy-audit-v1.md` | Done |
| Final synthesis | `docs/analysis/2026-06-06-anufriev-final-synthesis-v1.md` | Done |
| Decision matrix | `docs/analysis/2026-06-06-anufriev-strategy-decision-matrix.md` | Done |
| Strategy economics v2 | `docs/analysis/2026-06-08-anufriev-strategy-economics-v2.md` | Updated decision/economics layer with 77-video transcript union and fresh 6h grid |
| Participant dossiers v1 | `docs/analysis/2026-06-08-anufriev-participant-dossiers-v1.md` | Participant-level transfer matrix with evidence grades and project decisions |
| Setup registry | `exports/trading-mvp/experiments/setup_registry.json` | Research-only setup registry for current and planned signal families |
| Experiment ledger | `exports/trading-mvp/experiments/experiment_ledger.jsonl` | JSONL ledger for hypothesis/result/verdict tracking |
| Strategy playbook | `docs/analysis/2026-06-06-anufriev-strategy-playbook-v1.md` | Done |
| External evidence register | `docs/analysis/2026-06-06-anufriev-external-evidence-register.md` | Done |
| HFT/scalping source packet | `docs/analysis/2026-06-01-hft-scalping-kriticheskiy-razbor.md` | Done for 3 key videos |
| Fresh 6h signal-type maker grid | `exports/trading-mvp/backtests/ws_grid_search_signal_type_maker_quality_6h_20260608.json` | 472,583 events / 192 configs / 0 eligible |

## 3. Requirement-by-requirement status

| Requirement | Evidence | Status | Residual gap |
|---|---|---|---|
| Maximum number of videos | Full catalog 461; trading-relevant 287; all-287 metadata | Mostly achieved at metadata level | Transcript-level not complete |
| Strategies identified | Main audit, synthesis, playbook | Achieved for strategy families | Some older/general videos remain metadata-only |
| High win-rate claims analyzed | High-winrate cluster 60 videos; HFT source packet; synthesis | Partially achieved | Many high-return stories lack transcript-level verification |
| Strategy comparison | Decision matrix and synthesis | Achieved | Needs future update after `perp_replay` results |
| Participant comparison | Scorecards, decision matrix, synthesis, participant dossiers v1 | Achieved for key participants; partial for long-tail guests | Participant extraction is conservative; some high-view guests remain metadata-only |
| External truth check | External evidence register | Achieved for main claim families | Not every single video claim checked externally |
| Truth vs marketing distinction | Main audit, external register, synthesis | Achieved for key themes | Metadata-only videos need more manual transcript review |
| Compare with `trading_mvp` | Synthesis, decision matrix, playbook, 6h artifacts | Achieved | Needs update after next project experiment |
| Project corrections/pivot | Roadmap and implementation: `perp_replay` skeleton, sweep detector, quality/fill model, setup registry, experiment ledger | Achieved as research layer | Next step is to extend to real perp adapters/data and paper-forward validation |
| Economic model | Synthesis, decision matrix, strategy economics v2 | Achieved at branch level | More precise cost model requires live infra/vendor assumptions |
| Unified deliverable | Final synthesis + linked package | Achieved | Goal remains active only because transcript coverage is incomplete |

## 4. What is proven

1. The channel has substantial trading/crypto coverage: 287 relevant videos from 461 total.
2. The dominant channel themes are broad trading, high-return stories, AI/bots, risk/playbook, orderbook/market-maker, funding/passive, legal crypto, futures/derivatives, and news/regime.
3. Orderbook/tape ideas are relevant to `trading_mvp`, but current spot maker implementations failed EV gates.
4. Current `trading_mvp` should not go live:
   - `flow_continue`: 45 trades, 42.22% win-rate, net PnL -0.2065, PF 0.721.
   - `fade_exhaustion`: 77 trades, 45.45% win-rate, net PnL -0.4375, PF 0.648.
   - funding short horizon: 41 markets, 0 trades.
5. Best next research model is `perp long/short microstructure replay + liquidity sweep/reversal + market-quality/fill-probability + experiment ledger`.
6. External sources support the risk framing, not the profitability claims.

## 5. What is not proven

1. The channel does not prove a transferable 90% win-rate system.
2. Metadata-only high-return stories do not prove profitability.
3. Market-maker intent cannot be inferred from order-book patterns alone.
4. Current spot-only bot is not profitable.
5. AI trading claims are not proof of autonomous trading edge.
6. Funding/basis is not a high-frequency win-rate engine in current tests.

## 6. Blocking condition

Transcript-level completion is blocked by YouTube rate/IP limiting:

- `youtube-transcript-api`: 46 successful, 241 failed with IP block.
- `yt-dlp` timedtext/json3: 22 successful, then HTTP 429; those successes overlap the existing 46.
- Later retry batches via `tools/anufriev_transcript_retry.py`: 31 additional clean successes without HTTP 429.
- Latest retry check on 2026-06-08 added no new success: `gQ9f2fFnDn8` stopped with `HTTPError:429`, so clean retry output remains 31 successes plus 1 failure row.
- All 287 relevant videos have ru auto-caption metadata, but downloading/reading them at scale is currently rate-limited.

This is not a total impasse because metadata-level and key transcript-level analysis are already useful. It does prevent claiming full video-by-video transcript verification.

## 7. Next actions if continuing the analysis goal

1. Run `tools/anufriev_transcript_retry.py` later with `--sleep-sec 60` or higher and `--stop-on-rate-limit`.
2. Use `exports/youtube-anufriev/anufriev_transcript_retry_queue_20260606.csv` as the authoritative priority order.
3. Prioritize high-risk metadata-only claims already ranked in the queue:
   - top high-winrate/deposit-growth videos;
   - top orderbook/market-maker videos;
   - top futures/prop/perp videos;
   - top funding/basis/arbitrage videos.
4. Manually inspect 10-20 highest-impact metadata-only videos if timedtext remains blocked.
5. Update synthesis after new transcript coverage.
6. In parallel, extend `perp_replay` with real perp adapters/data and paper-forward validation.

## 8. Completion status

Current state: not complete against the full original objective if "all possible videos/claims" means transcript-level verification.

Current state: sufficient for next engineering decision, because:
- channel map is complete at metadata level for 287 relevant videos;
- key strategy families are identified;
- external risk check is documented;
- current project fit is tested against real `trading_mvp` artifacts;
- the next project step is concrete and gated.
