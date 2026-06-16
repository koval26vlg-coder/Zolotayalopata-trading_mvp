# Funding Paper-Forward Sample Gate

Дата: 2026-06-15

## Цель

Усилить acceptance gate для `funding-paper-forward`: forward-проверка не должна считаться принятой только по PnL/duration, если выборка слишком мала по числу строк или рынков.

## Реализовано

- `funding-paper-plan` теперь сохраняет:
  - `min_forward_rows`
  - `min_forward_markets`
- Defaults для новых frozen plans:
  - `min_forward_rows=20`
  - `min_forward_markets=1`
- `funding-paper-forward` теперь добавляет в coverage:
  - `min_forward_rows`
  - `min_forward_markets`
  - `rows_accepted`
  - `markets_accepted`
- `paper_acceptance.accepted=false`, если:
  - rows меньше `min_forward_rows`
  - markets меньше `min_forward_markets`
- Причины отказа:
  - `min_forward_rows`
  - `min_forward_markets`

## Измененные участки

- `trading_mvp/src/basis.py`
  - `create_funding_paper_forward_plan_file`
  - `_funding_forward_coverage`
  - `_funding_paper_forward_acceptance`
- `trading_mvp/src/cli.py`
  - `funding-paper-plan --min-forward-rows`
  - `funding-paper-plan --min-forward-markets`
- `trading_mvp/run_mvp.ps1`
  - `-FundingPaperMinForwardRows`
  - `-FundingPaperMinForwardMarkets`
- `trading_mvp/tests/test_basis.py`
  - plan serialization test
  - paper-forward sample rejection test
  - CLI parser coverage

## Проверка

Targeted tests:

```powershell
& 'C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe' -m unittest trading_mvp.tests.test_basis
```

Результат:

```text
Ran 35 tests in 0.196s
OK
```

Full suite:

```powershell
& 'C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe' -m unittest discover -s trading_mvp\tests
```

Результат:

```text
Ran 107 tests in 0.235s
OK
```

PowerShell smoke:

```json
{
  "planOk": true,
  "minRows": 3,
  "minMarkets": 2,
  "forwardOk": true,
  "accepted": false,
  "reasons": "min_forward_rows,min_forward_markets",
  "rows": 2,
  "markets": 1,
  "rowsAccepted": false,
  "marketsAccepted": false,
  "liveOrders": false
}
```

## Статус 24h Funding Collect

```json
{
  "status": "running_or_waiting",
  "ready_for_postprocess": false,
  "final": false,
  "completed_cycles": 17,
  "cycles": 288,
  "remaining_cycles": 271,
  "progress_pct": 5.902777777777778,
  "manifest_rows": 384,
  "line_count": 384,
  "line_count_matches_manifest": true,
  "errors": 98,
  "last_write_age_sec": 158.30421257019043,
  "stale_after_sec": 900.0
}
```

Postprocess не запускался, потому что manifest еще не финальный.

## Следующий Gate

Когда 24h collect станет final:

1. Запустить `funding-postprocess` с OOS и stress gates.
2. Создать frozen `funding-paper-plan` только при `research_acceptance.accepted=true`.
3. Собрать отдельный forward dataset.
4. Запустить `funding-paper-forward`.
5. Принимать forward только если одновременно проходят:
   - net PnL after fees/slippage
   - winrate
   - expectancy
   - drawdown
   - trade sample size
   - duration coverage
   - row sample size
   - market sample size

