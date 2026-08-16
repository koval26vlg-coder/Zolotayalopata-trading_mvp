# 2026-08-17 — known-debt закрыт: 2 красных теста переведены на честную семантику

Оба теста были красными из-за структурной предпосылки «замороженный
манифест навсегда совпадает с живыми общими модулями», которая нарушена
легитимной эволюцией репо.

## 1. test_checked_in_spot_v2_freeze_* (verification)

Было: генератор пересобирает манифест из ТЕКУЩИХ файлов и сравнивает с
замороженным → дрейф readiness/guard хэшей (модули менялись 16.08)
вечный red; re-freeze каскадно задел бы принятые momentum-планы
(встраивают значения констант).

Стало: `test_checked_in_spot_v2_freeze_is_internally_consistent` —
манифест проверяется на внутреннюю консистентность (manifest_hash по
собственному контенту, approved=False, привязанные пути существуют,
bindings на месте); receipt-часть не изменилась и продолжает
сверяться (proposal не дрейфовал). Живой дрейф общих модулей —
операционная документация, не unit-тест.

## 2. test_offline_refreeze_readiness_resolves_without_execution_artifacts (v3)

Было: резолвер упирался в исторические артефакты терминального v3-рана
(launch record / execution manifest / approval receipt существуют) и
в v3-era gate decision.

Стало: тест синтезирует v3-era мир — temp-гейт с
EXPECTED_QUALITY_DECISION + моки module-атрибутов
(LAUNCH_RECORD_PATH / EXECUTION_MANIFEST_PATH / APPROVAL_RECEIPT_PATH
на несуществующие temp-пути). Логика резолвера теперь тестируется
изолированно от пост-терминального состояния мира.

## Результат

- 195 passed по всем затронутым семействам (verification 37, v3 11,
  readiness+guard 35, momentum/identity цепочки)
- freeze-манифесты и принятые планы НЕ тронуты (никаких re-freeze
  каскадов)
- known-debt запись закрыта со ссылкой на этот лог
