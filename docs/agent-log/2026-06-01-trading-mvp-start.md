# Запрос
Пользователь подтвердил запуск работ по MVP алготрейдинга: `collector -> backtester -> executor -> risk-engine` с фокусом на автоматизированный контур и testnet/paper режим.

# Результат
Добавлен новый модуль `automations/trading_mvp`:
- `README.md` с пошаговым запуском;
- `config.example.json` и рабочий `config.json`;
- `run_mvp.ps1`;
- `src/config.py` (датаклассы конфига), `src/collector.py` (сбор снапшотов через Binance Spot Testnet REST), `src/trading.py` (стратегия, риск-движок, бэктестер, testnet-исполнитель), `src/cli.py` (CLI команды `collect/backtest/run`);
- `tests/test_risk.py`, `tests/test_backtester.py`.

Ключевые ограничения риска в коде:
- лимит нотионала/позиции/числа сделок в день;
- дневной лимит убытка с активацией kill-switch;
- блокировка новых входов при активном kill-switch.

# Проверки
Выполнено успешно:
1. `python -m unittest discover -s automations\\trading_mvp\\tests -p "test_*.py"` -> `Ran 3 tests ... OK`.
2. CLI smoke:
   - `collect --seconds 2` -> создан `exports/trading-mvp/raw/BTCUSDT_*.jsonl`;
   - `backtest` -> создан `exports/trading-mvp/backtests/backtest_BTCUSDT_*.json`;
   - `run --mode paper --cycles 2` -> создан `exports/trading-mvp/run/run_BTCUSDT_paper_*.json`.

# Риски
- Сборщик MVP использует REST polling, не WebSocket L2; для HFT-уровня потребуется отдельный low-latency поток.
- `live-testnet` требует корректных `BINANCE_API_KEY/BINANCE_API_SECRET` и ликвидности на тестнете.
- Базовая стратегия эвристическая; без расширенного out-of-sample и комиссии/проскальзывания масштабировать нельзя.

# Следующему
1. Включить WebSocket collector (diff depth + trades) и локальную реконструкцию стакана.
2. Добавить комиссии/проскальзывание как обязательные параметры бэктеста.
3. Вынести логику исполнения в отдельный state-machine с retry/идемпотентностью по `clientOrderId`.
