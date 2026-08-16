# 2026-08-16 — first-days proxy-date descriptive census

Детерминированный offline census собранных first-days окон (класс
`PROXY_DATE_DESCRIPTIVE_CENSUS`, acceptance_decision =
`NONE_DESCRIPTIVE_ONLY`). Источник: run
`slow_liquidity_listing_momentum_first_days_collect_20260816`
(`output_sha256=a44b7daf…`, manifest COMPLETED).

- census `exports/trading-mvp/analysis/slow_liquidity_listing_momentum_first_days_census_20260816.json`
- `census_hash=682a88dfccc8ecc16c18d70646ed7658f4ff62043a8c05f2d96cbad245c9fca5`
- primary окна: 363 (mexc 358 / gateio 5); reconciliation флагов сходится с
  manifest (request_error 426, no_data 3, truncated 3, short 3)

## Описательные результаты (primary окна)

- MEXC (n=358): ret_72h median **+113.7%**, mean +297%, p10 −15.4%,
  p90 +654%; share>0 **85.2%**; max_runup median +214%
- Gate (n=5, только свежие листинги из-за лимита 10000 точек): median
  −20.5% — выборка мала, не интерпретировать
- По году листинга: 2022–2023 (n=68) median +143% / 94%>0; 2024–2025
  (n=235) +98% / 83%>0; 2026 (n=28) +129% / 82%>0; ≤2019 (n=4) −11%

## Интерпретация — строго с ограничениями контракта

1. **Survivorship-bias доминирует.** Universe = текущий снапшот живых пар
   MEXC; листинги, завершившиеся делистингом (обнулением), отсутствуют
   по построению. 85%>0 и median +114% — верхняя граница артефакта
   выживших, НЕ tradable edge.
2. Ретроспективное PROXY_DATE доказательство по контракту не может
   дать ACCEPT; терминальный ACCEPT требует forward-выборки новых
   листингов, где survivorship ещё не подействовал.
3. Практический вывод по ветке: ретроспектива закрыта как descriptive;
   содержательно полезное продолжение — forward-мониторинг новых
   листингов (MEXC+Gate, свежие даты в пределах глубины Gate), отдельным
   планом с расписанием.

Тесты: 10 passed (`test_slow_liquidity_listing_momentum_first_days_census.py`),
включая сверку с реальными данными сбора (795/363/флаги).

## Receipt
Родительская цепочка: proxy acceptance receipt → collect plan
`c4834950…` → данный census (детерминированный postprocess, gate
READY_FOR_POSTPROCESS).

## Next
Forward-listing monitor PlanOnly (календарь + инкрементальные новые
листинги, visible, bounded) — кандидат на следующий шаг; evaluator/OOS
по ретроспективе не запускаем (bias).
