## Архитектурный Review: trading_mvp (Spot/Perp Basis Mean Reversion)

### 1. GATE SAFETY ✓ PASS

| Параметр | Статус |
|----------|--------|
| active-run-gate.json | READY_FOR_POSTPROCESS ✓ |
| Текущая ветка | spot_perp_basis_mean_reversion_no_funding ✓ |
| replay_allowed | false ✓ |
| grid_allowed | false ✓ |
| live_orders | false ✓ |
| api_keys | false ✓ |
| leverage_or_margin | false ✓ |
| paper_forward_allowed | false ✓ |
| requires_explicit_user_approval_for_public_probe | true ✓ |

---

### 2. P0 (BLOCKING) FINDINGS
**Нет.**

---

### 3. P1 (HIGH PRIORITY) FINDINGS

| № | Файл | Строка | Проблема | Причина |
|---|------|--------|---------|---------|
| 1 | `trading_mvp/src/funding.py` | 120 | Русский текст ошибки в англоязычной кодовой базе | `raise RuntimeError(f"Не удалось выполнить GET {url}")` → сломаны логи в EN окружении |
| 2 | `trading_mvp/src/funding.py` | 237–240 | _tickers_cache не имеет TTL | MexcFundingClient закэширует тикеры один раз на всю сессию; стоп-loss на обновление если probe > 1 часа |
| 3 | `trading_mvp/src/funding.py` | 109–119 | Тайм-ауты и retry слишком тугие | 3 попытки × (0.5–1.0 сек ожидание) + глобальный 10-сек timeout → может потеряться funding_rate на медленных сетях |

---

### 4. P2 (MEDIUM PRIORITY) FINDINGS

| № | Файл | Строка | Проблема | Причина |
|---|------|--------|---------|---------|
| 1 | `trading_mvp/src/spot_perp_basis_public_probe.py` | 87–88 | Проверка bid < ask без epsilon | Floating-point сравнение на микроспредах (99.999999 vs 100.000001) |
| 2 | `trading_mvp/src/spot_perp_basis_public_probe.py` | 120, 195–196 | Несогласованность символов: MEXC spot=AEROUSDT, perp=AERO_USDT | Риск ошибок при ручном обновлении списков |
| 3 | `trading_mvp/src/spot_perp_basis_public_probe.py` | 284–305 | `paired_base_ok()` не проверяет диапазоны значений | Базис=0, спред=NaN, funding=∞ пройдут проверку |
| 4 | `trading_mvp/tests/test_spot_perp_basis_public_probe.py` | 38–81 | `_probe_mexc()` и `_probe_gateio()` не покрыты unit-тестами | Нет мок-тестов для реальной логики обмена (только тесты парсера) |

---

### 5. МОЖНО ЛИ ЗАПУСТИТЬ PUBLIC PROBE?

**✓ ДА, после явного подтверждения пользователя.**

**Команда:**
```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File "C:\Users\koval\Documents\ZolotyayLopata\tools\trading_spot_perp_basis_public_probe.ps1" `
  -PreflightPath "C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\analysis\spot_perp_basis_availability_preflight_20260709_112347.json" `
  -MaxBases 10 -MinSuccessBases 5 -DepthLimit 5 -TimeoutSec 10 `
  -ConfirmedPublicProbe -UpdateGate -Json
```

**Scope:**
- 10 non-Binance баз (AERO, ARX, B, BAS, BASED, BIRB, BSB, BTW, DEEP, ESPORTS)
- 2 биржи (MEXC, Gate.io) × 2 venue (spot, perp)
- 8 полей (mid, spread, depth, funding, next_funding_ts)
- **Только публичные API**, snapshots для плана collect, ~10 сек timeout
- **Без сохранения данных, без collect/backtest/replay**

---

### 6. ДО LONG COLLECT / BACKTEST ИСПРАВИТЬ

**Обязательно (P1):**
1. `funding.py:120` → англ. сообщение об ошибке
2. `funding.py:237–240` → добавить TTL для _tickers_cache (e.g., 300 сек)

**Рекомендуется (P2):**
3. `spot_perp_basis_public_probe.py:87–88` → epsilon-безопасное сравнение bid/ask
4. Централизовать логику MEXC spot/perp символов (AEROUSDT vs AERO_USDT)
5. `paired_base_ok()` → валидация диапазонов (mid > 0, spread ∈ [0, 100] bps, funding ∈ [-0.01, 0.01])
6. Добавить mock-тесты для `_probe_mexc()` и `_probe_gateio()`

---

### 7. ЗАПРЕЩЕНО НА ЭТОМ ЭТАПЕ

- ❌ **replay** (replay_allowed=false)
- ❌ **grid-search** (grid_allowed=false)
- ❌ **live orders** (live_orders=false)
- ❌ **API keys** (api_keys=false)
- ❌ **leverage/margin** (leverage_or_margin=false)
- ❌ **paper-forward** (paper_forward_allowed=false)
- ❌ **actual collect** (требует отдельного подтверждения после успешного probe)
- ❌ **code edits** к стратегии/collect/replay логике
- ❌ **backtest/postprocess** существующих данных

**Следующий шаг** (если probe примет ≥5 баз): построить видимый collect approval packet + дождаться юзер-подтверждения.
