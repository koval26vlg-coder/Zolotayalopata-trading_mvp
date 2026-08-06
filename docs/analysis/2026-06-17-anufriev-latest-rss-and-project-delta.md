# Anufriev Latest RSS Delta And Project Decision Update

Дата: 2026-06-17  
Статус: research-only addendum к `2026-06-08-anufriev-strategy-economics-v2.md`. Не является инвестсоветом, юридической консультацией или рекомендацией к live-торговле.

## 1. Что обновлено

После завершения 24h funding/basis collect и postprocess был проверен актуальный RSS канала:

- Канал: `https://www.youtube.com/@AnufrievNikita/`
- RSS: `https://www.youtube.com/feeds/videos.xml?channel_id=UCDy8-SKJCvcp4SegONQJItw`
- Raw RSS snapshot: `exports/youtube-anufriev/anufriev_youtube_rss_20260617.xml`
- Parsed latest CSV: `exports/youtube-anufriev/anufriev_youtube_rss_latest_20260617.csv`
- Delta CSV: `exports/youtube-anufriev/anufriev_youtube_rss_delta_20260617.csv`

Все 15 последних RSS-видео отсутствовали в полном каталоге от 2026-06-06. Это ожидаемо: после каталога канал продолжил активно публиковать Shorts.

## 2. Последние видео и применимость

| Date | Video | Theme | Project implication |
|---|---|---|---|
| 2026-06-17 | `Как сейчас легально менять крипту на рубли?` | P2P / legal / fiat off-ramp | Усиливает compliance/withdrawal-risk слой; не alpha для trading bot |
| 2026-06-16 | `Работают ли инвестиции в крипту в долгосрок?` | Long-term crypto investing | Отдельная portfolio/cycle тема; не intraday/high-winrate bot |
| 2026-06-16 | `Никогда не слушай советы таких людей!` | Advice / psychology | Поддерживает правило: не брать claim как сигнал без replay/evidence |
| 2026-06-16 | `Все твои транзакции доступны налоговой!` | Tax / reporting risk | Усиливает legal/tax risk card перед любым live-like этапом |
| 2026-06-16 | `За P2P блокируют карты! Как выводить крипту в 2026?` | P2P / bank blocking | Не торговый edge; операционный риск fiat rails |
| 2026-06-16 | `Перевела деньги, а сделку попросили отменить!` | P2P fraud / operational risk | Не использовать P2P как часть проекта без отдельной risk model |
| 2026-06-16 | `Реально ли сейчас пользоваться P2P без проблем с банками?` | P2P risk | Подтверждает, что P2P ветка должна быть исключена из MVP trading execution |
| 2026-06-15 | `Как отдыхать так, чтобы реально отдохнуть?` | Self-management | Непрямая ценность: режим, fatigue, playbook discipline |
| 2026-06-15 | `Чем русские отличаются от американцев?` | Other | Нет прямого влияния на trading_mvp |
| 2026-06-15 | `А сколько вы максимально готовы отдать за футболку?` | Other | Нет прямого влияния на trading_mvp |
| 2026-06-15 | `Поставил стоп, цена коснулась и улетела! Как избегать этого?` | Stops / liquidity sweep | Поддерживает sweep/reclaim гипотезу, но не доказывает edge |
| 2026-06-15 | `Не стремись разбогатеть быстро! Вот что важнее` | Risk psychology | Совпадает с отказом от high-winrate/fast-profit KPI |
| 2026-06-15 | `Миру не нужны копии, миру нужен ты!` | Self-development | Нет прямого alpha |
| 2026-06-14 | `Как смотреть объемы на графике бесплатно?` | Volume / market data | Поддерживает trade-flow density / volume feature layer |
| 2026-06-14 | `На фандинге можно зарабатывать хорошие проценты` | Funding carry | Прямо релевантно funding module; текущий project evidence не подтвердил положительную экономику на 24h |

## 3. Внешняя проверка свежих тем

### P2P / налоги / fiat off-ramp

Свежие Shorts сильно сместились в legal/P2P/off-ramp risk. Это важно для проекта, но не как торговая стратегия.

Проверочные источники:

- Банк России прямо описывает высокорисковые P2P-операции, связанные с приобретением криптовалюты, как проблему для банковского контроля.
- Банк России отдельно предупреждает о риске вовлечения клиентов нелегальных криптообменников в финансирование преступной деятельности.
- ФНС указывает, что цифровая валюта признается имуществом, а доход от продажи криптовалюты облагается НДФЛ.

Project decision:

- Не строить P2P/off-ramp модуль как часть trading_mvp.
- Перед любым live-like этапом нужна venue/fiat/off-ramp risk card.
- Для research-only bot это остается compliance context, а не alpha.

### Funding carry

Свежий Short про funding совпадает с нашим выбранным отдельным модулем `funding/basis carry engine`, но локальная экономика после завершенного 24h collect негативная.

Project evidence:

- Collect: `288/288` cycles, `7659` rows, `30` markets, `824` errors.
- Data span: about `30.51h`.
- Data quality after relaxed `min_rows_per_cycle=15`: accepted.
- Rank eligible after economics gates: `0`.
- Backtest trades: `0`.
- Research acceptance: rejected.

Core reason:

- Даже лучшие rows имеют funding около `0.18-2.01 bps` за интервал.
- Round-trip cost model около `39 bps`.
- Поэтому `expected_net_carry_bps` и `risk_adjusted_edge_bps` отрицательные, а break-even horizon часто сотни часов.

Project decision:

- Funding не умер как направление, но текущая модель `taker-like fees + 1 interval hold` не жизнеспособна.
- Следующий funding шаг должен быть не live/paper trade, а:
  - multi-week collection;
  - maker/VIP fee sensitivity;
  - longer hold intervals;
  - basis-risk stress;
  - exchange/venue risk constraints.

### Stops / volume / liquidity sweep

Новые Shorts про стопы и объемы поддерживают старую thesis: важны не свечные паттерны, а flow/volume/sweep/reclaim.

Project evidence:

- Spot maker `flow_continue` and `fade_exhaustion`: failed EV gates.
- Event-quality layer: raw sweep/reclaim labels had enough observations for analysis, but were not selective enough for high-winrate acceptance.
- Breakout/OOS note from Claude: in-sample edge did not survive holdout; 6h dataset фактически покрывал слишком малую независимую выборку.

Project decision:

- Не расширять текущий short-sample breakout.
- Не запускать live/paper-forward по sweep/reclaim.
- Нужна длинная независимая плотная WS/perp выборка: минимум часы/сутки, лучше несколько дней, прежде чем снова тестировать intraday signal families.

## 4. Обновленный verdict по стратегиям

| Branch | Previous verdict | 2026-06-17 update | Decision |
|---|---|---|---|
| Perp/sweep microstructure | Highest research priority, unproven | Latest stop/volume Shorts support hypothesis but not proof | Keep as research-only; needs longer dense data |
| Funding/basis carry | Separate promising module, longer horizon | Fresh channel theme supports it; 24h project evidence rejects current cost model | Continue only as multi-week research, not paper/live |
| P2P/off-ramp | Compliance/risk context | Latest channel batch is heavily P2P/legal | Keep outside trading bot; add risk card before live-like operations |
| High-winrate / fast profit | Reject as KPI | New psychology/advice Shorts support caution | Keep EV gates; no winrate-only optimization |
| Volume tooling | Useful feature layer | Latest volume Short reinforces data tooling | Add volume/trade-flow density as market-quality feature, not standalone signal |

## 5. Current strongest conclusion

The channel's latest posts do not justify changing into live trading. They reinforce a stricter version of the roadmap:

1. Keep `trading_mvp` research-only.
2. Treat funding carry as separate from intraday microstructure.
3. Do not touch P2P/off-ramp as an execution path; keep it as legal/operational risk.
4. Do not continue breakout/HFT claims on thin samples.
5. Next high-value data step is a visible, condition-gated long collection:
   - funding/basis: multi-week;
   - intraday/perp: dense WS/perp for several days;
   - no background launches without explicit approval.

## 6. Immediate project correction

Based on the completed 24h funding run and latest channel delta:

- Update the current strategy status to `research_rejected_current_config`.
- Keep the module, but freeze current parameters as failed:
  - taker-like cost;
  - one funding interval hold;
  - min positive net carry after costs;
  - no maker/VIP assumption.
- The next viable funding experiment must explicitly test whether lower fees and longer holding horizon can overcome cost and basis risk. If not, funding carry should remain watchlist-only.

## 7. Sources

- YouTube channel: `https://www.youtube.com/@AnufrievNikita/`
- YouTube RSS snapshot: `https://www.youtube.com/feeds/videos.xml?channel_id=UCDy8-SKJCvcp4SegONQJItw`
- Bank of Russia, high-risk P2P statements: `https://www.cbr.ru/press/event/?id=18459`
- Bank of Russia, illegal crypto exchanger risk warning: `https://cbr.ru/press/event/?id=24706`
- FNS, crypto sale income / NDFL: `https://www.nalog.gov.ru/rn25/ifns/r25_03/info/16604994/`
- Local funding postprocess: `exports/trading-mvp/funding/funding_postprocess_24h_spotliq_relaxed15_20260615_202709.json`
