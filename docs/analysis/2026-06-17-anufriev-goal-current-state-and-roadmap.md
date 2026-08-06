# Anufriev / trading_mvp Current State And Roadmap

Дата: 2026-06-17  
Статус: рабочий consolidated audit активной цели. Research-only; не является инвестсоветом, юридической консультацией или рекомендацией к live-торговле.

## 1. Что уже покрыто по цели

| Требование цели | Текущий статус | Evidence |
|---|---|---|
| Изучить максимум канала | Есть карта канала: `461` видео всего, `287` trading/crypto/investing-релевантных | `exports/youtube-anufriev/anufriev_video_catalog_20260606.csv`, `exports/youtube-anufriev/anufriev_trading_relevant_scorecard_all287_with_retry_20260606.csv` |
| Проверить свежие видео | Проверен RSS от 2026-06-17; `15` последних видео были новыми относительно каталога 2026-06-06 | `exports/youtube-anufriev/anufriev_youtube_rss_latest_20260617.csv`, `docs/analysis/2026-06-17-anufriev-latest-rss-and-project-delta.md` |
| Получить transcript-backed claims | Есть `77` уникальных transcript-backed видео; `210` metadata-only из-за YouTube timedtext/IP rate limit | `exports/youtube-anufriev/anufriev_transcript_coverage_union_20260606.json`, summary JSON |
| Выделить стратегии | Основные families выделены: microstructure/perp, sweep/reclaim, funding carry, AI tooling, risk/playbook, P2P/legal, news/regime, high-winrate stories | `docs/analysis/2026-06-08-anufriev-strategy-economics-v2.md` |
| Сравнить участников | Participant dossiers есть, но часть строк metadata-heavy | `docs/analysis/2026-06-08-anufriev-participant-dossiers-v1.md` |
| Проверить правдивость | Основные claim families проверены внешними регуляторными/академическими источниками; индивидуальные доходности не доказаны | `docs/analysis/2026-06-06-anufriev-external-evidence-register.md` |
| Сравнить с `trading_mvp` | Есть experiment ledger и replay/backtest artifacts | `exports/trading-mvp/experiments/experiment_ledger.jsonl` |
| Экономическая модель | Есть branch-level economics; текущие tested branches не прошли gates | `docs/analysis/2026-06-08-anufriev-strategy-economics-v2.md`, funding postprocess |

Вывод: цель существенно продвинута, но не завершена. Полного transcript-level покрытия всех 287 релевантных видео нет, а жизнеспособная стратегия с доказанным high-winrate/positive-EV еще не найдена.

## 2. Свежий канал: что изменилось 2026-06-17

RSS batch от 2026-06-17 усилил три темы:

| Тема | Видео | Вывод для проекта |
|---|---|---|
| Funding carry | `На фандинге можно зарабатывать хорошие проценты` | Funding остается отдельной веткой, но текущая 24h экономика не прошла gates |
| P2P / legal / tax / bank risk | `Как сейчас легально менять крипту на рубли?`, `Все твои транзакции доступны налоговой!`, `За P2P блокируют карты!` | P2P не alpha для bot; это compliance/off-ramp risk layer |
| Stops / volume | `Поставил стоп, цена коснулась и улетела!`, `Как смотреть объемы на графике бесплатно?` | Поддерживает sweep/volume hypotheses, но не доказывает edge |

Decision: свежие видео не дают основания включать live trading. Они усиливают текущий evidence-first roadmap.

### RSS refresh 2026-06-17 16:40

Короткая повторная RSS-проверка в 16:40 показала еще `2` новых Shorts относительно snapshot `anufriev_youtube_rss_latest_20260617.csv`:

| Time | Video | Theme | Project implication |
|---|---|---|---|
| 2026-06-17 16:00 | `Как сейчас покупать крипту без 115 ФЗ?` | 115-ФЗ / fiat rails / bank risk | Усиливает live-readiness и off-ramp risk card; не alpha |
| 2026-06-17 15:00 | `Где безопаснее хранить крипту?` | Custody / wallet / venue risk | Усиливает custody/venue risk checklist перед live-like этапом; не trading signal |

Новые локальные артефакты:

- `exports/youtube-anufriev/anufriev_youtube_rss_refresh_20260617_164026.xml`
- `exports/youtube-anufriev/anufriev_youtube_rss_refresh_20260617_164026.csv`
- `exports/youtube-anufriev/anufriev_youtube_rss_refresh_delta_20260617_164026.csv`
- `docs/analysis/2026-06-17-anufriev-latest-two-source-packet.md`

Decision update: последние публикации канала все сильнее подтверждают, что перед любым live-like этапом нужен не только trading edge, но и отдельный compliance/custody/venue/off-ramp gate.

Evidence note: по двум новым Shorts transcript extraction пока не сработал. Watch pages показывают caption tracks, но direct timedtext по русским captions возвращает пустое тело, а один translated-track check дал HTTP 429. Поэтому эти два видео используются только как metadata-level theme evidence.

## 3. Strategy Verdict Matrix

| Strategy family | Channel appeal | Current project evidence | Verdict |
|---|---|---|---|
| Spot maker order-book continuation | Простая стаканная логика, market flow | 6h maker grid: `flow_continue` 45 trades, win rate `42.22%`, net PnL `-0.2065`, PF `0.721` | Rejected |
| Spot maker fade/exhaustion | Контртренд после истощения потока | 6h maker grid: 77 trades, win rate `45.45%`, net PnL `-0.4375`, PF `0.648` | Rejected |
| Perp long/short microstructure | Лучше соответствует stop cascades и short-side ideas | Clean duration-bound perp grid: `0` eligible configs; flow/fade materially negative; LSR positive only on `3` trades | Rejected current signal family |
| Liquidity sweep/reclaim events | Ближе всего к тезисам про стопы и ликвидность | Event layer: `1018` sweeps, reclaim rate `70.63%`, but target-before-stop only `36.72%`, false-sweep rate `74.07%` | Inconclusive diagnostic only |
| Liquidity sweep replay v2 | Лучший event slice из in-sample | Maker: 10 trades, win rate `10%`, net `-0.3901`; taker: 35 trades, win rate `2.86%`, net `-1.9395` | Rejected |
| Large-move breakout | Попытка уйти от мелкого scalp в крупный TP | Train: 8 trades, 75% win, PF 4.74; OOS: 2 trades, 50% win, PF 0.97, net `-0.002` | Rejected as overfit/thin sample |
| Funding/basis carry | Свежая тема канала и реальный mechanism | 24h collect: `7659` rows, `30` markets, rank eligible `0`, backtest trades `0` | Failed current cost model |
| P2P/off-ramp | Много свежих Shorts | Регуляторный/операционный риск, не торговый edge | Exclude from trading bot |
| AI trading | Большой кластер канала | Полезно для tooling, monitoring, classification; не доказательство alpha | Use as tooling only |
| Risk/playbook/process | Сильная повторяющаяся тема | Напрямую полезно: gates, ledger, kill-switch, no live before proof | Mandatory |

## 4. Почему high-winrate пока нельзя считать найденным

High win-rate сам по себе не является целью системы. Рабочая цель должна быть:

`positive expected value after fees/slippage/funding/spread/fill-risk + enough trades + OOS/walk-forward/stress pass`

Текущие проверки показывают обратное:

- Малые in-sample wins не переживают holdout.
- Sweep/reclaim дает красивые narrative labels, но execution replay ломает edge.
- Funding payouts на коротком горизонте слишком малы относительно round-trip costs.
- Spot-only стаканная логика ограничена отсутствием short-side и страдает от adverse selection.

Значит, оптимизация под winrate без EV gates запрещена.

## 5. Funding Branch: текущая экономика

24h spot-liquidity funding collect:

- Rows: `7659`.
- Cycles: `288/288`.
- Markets: `30`.
- Error rate: about `9.7%`.
- Data quality: accepted under relaxed `min_rows_per_cycle=15`.
- Rank eligible: `0`.
- Persistence eligible: `23`.
- Backtest trades: `0`.
- Research acceptance: false; reasons: `full_backtest_rejected`, `oos_rejected`, `walk_forward_rejected`.

Core blocker:

- Typical funding rows are around `0.18-2.01 bps` per interval.
- Current round-trip cost model is about `39 bps`.
- Example HYPE/MEXC: funding about `0.5 bps`, expected net carry about `-38.5 bps`, break-even about `312h`.

Decision:

- Funding is not dead as a research branch.
- Current `taker-like cost + one interval hold` model is dead.
- Next funding experiment must test longer horizon, lower maker/VIP-like fee assumptions, funding persistence, basis-risk stress, and real flip/exit behavior.

## 6. Microstructure Branch: текущая экономика

The channel's microstructure ideas remain useful as hypotheses, not as proof.

Current failed/inconclusive evidence:

- `flow_continue`: negative EV on spot maker and perp replay.
- `fade_exhaustion`: more activity but worse economics.
- `liquidity_sweep_reversal`: labels are plentiful, but selectivity is weak and replay v2 failed.
- `large_move_breakout`: in-sample positive, OOS failed, sample too thin.

Decision:

- Do not tune more parameters on the existing thin sample.
- Do not launch paper/live on any current intraday signal.
- If this branch continues, first collect a dense independent multi-day WS/perp dataset, then rerun replay with frozen gates.

## 7. Participant Transfer Map

| Participant / theme | What transfers to project | What does not transfer |
|---|---|---|
| Андрей Демченко / стакан | L2/tape review, avoid saturated mega-cap markets, observable order-book features | Claims like 90% win-rate without reproducible replay |
| Михаил Латогузов / playbook | Briefing, setup database, daily risk limits, repeatable setup discipline | Manual intuition as bot alpha |
| Нарэк Григорян / market-maker narratives | Stop cascade and sweep/reclaim hypotheses | Intent claims about manipulation without observable proof |
| Funding/passive crypto guests | Funding/basis as separate carry module | Treating funding as HFT signal |
| Legal/P2P guests | Compliance, bank/off-ramp risk | P2P as MVP trading edge |
| AI/product guests | Automation, classification, research acceleration | AI-generated signals bypassing deterministic gates |

## 8. Current Product Decision

The defensible product is not a live "HFT/high-winrate bot" today.

The defensible product direction is:

`research engine for non-Binance markets -> evidence ledger -> visible long data collection -> strict postprocess/OOS/walk-forward/stress -> only then paper-forward`

Current priority order:

1. Funding/basis multi-day research because it is structurally cleaner than overfit intraday signals.
2. Dense multi-day perp/WS data only after approval because existing sample is too thin.
3. Market-quality/fill/adverse-selection analytics as required filters.
4. Risk/playbook/live-readiness checklist before any live-like phase.

Live-readiness gate is now explicit:

- `docs/analysis/live-readiness-checklist.md`

Single entry point for the full evidence base:

- `docs/analysis/2026-06-17-anufriev-master-evidence-index.md`

## 9. Next Concrete Step

Prepared visible launcher:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\start_funding_collect_visible.ps1 -Days 7 -ConfirmedLongRun
```

This should be launched only after explicit user confirmation because it is a long-running collector. While it is `RUNNING`, the active-run gate blocks other goal work except short status/ETA checks.

After final manifest:

1. Run funding postprocess/final-review.
2. Run OOS, walk-forward, stress and cost sensitivity.
3. Update experiment ledger.
4. Decide whether funding moves to paper-forward or remains watchlist-only.

## 10. Completion Gap

The active goal should stay open because:

- not all relevant videos are transcript-backed;
- no strategy has passed strict profitability gates;
- no multi-week funding evidence exists yet;
- no dense independent multi-day intraday dataset has been validated;
- no paper-forward candidate is accepted.

Next meaningful proof artifact is a visible 7d funding/basis collect plus postprocess, not another small in-sample grid.

## 11. Sources

- YouTube channel: `https://www.youtube.com/@AnufrievNikita/`
- YouTube RSS: `https://www.youtube.com/feeds/videos.xml?channel_id=UCDy8-SKJCvcp4SegONQJItw`
- Local latest RSS delta: `exports/youtube-anufriev/anufriev_youtube_rss_delta_20260617.csv`
- Strategy economics: `docs/analysis/2026-06-08-anufriev-strategy-economics-v2.md`
- Latest RSS delta analysis: `docs/analysis/2026-06-17-anufriev-latest-rss-and-project-delta.md`
- Funding postprocess: `exports/trading-mvp/funding/funding_postprocess_24h_spotliq_relaxed15_20260615_202709.json`
- Experiment ledger: `exports/trading-mvp/experiments/experiment_ledger.jsonl`
- External references used in prior audit: SEC HFT literature review, FCA HFT research, CFTC spoofing enforcement, ESMA perpetual futures/CFD statement, FINRA Rule 2270, Barber/Lee/Liu/Odean day-trading study, IOSCO crypto-asset market recommendations, Bank of Russia P2P/illegal exchanger warnings, FNS crypto-income tax note.

