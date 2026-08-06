# Funding Cost Assumption Gate

Дата: 2026-06-17  
Статус: read-only gate для funding/basis economics.

## Purpose

`tools/funding_cost_assumption_gate.ps1` не дает принять funding/basis strategy на основании lower-fee, maker/VIP или zero-cost sensitivity, если нет реального non-secret подтверждения account fee tier.

Текущий expected decision:

```text
USE_CURRENT_COST_ONLY_FOR_ACCEPTANCE
```

Причина: нет accepted artifact с реальными maker/taker fee tiers по `MEXC` и `Gate`.

## Commands

Readable:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\funding_cost_assumption_gate.ps1
```

JSON:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File C:\Users\koval\Documents\ZolotyayLopata\tools\funding_cost_assumption_gate.ps1 -Json
```

Shortcut:

```text
C:\Users\koval\Documents\ZolotyayLopata\TRADING_FUNDING_COST_GATE.cmd
```

## Current Rules

- `current_taker_like` is the only acceptance scenario.
- `reduced_fee`, `maker_vip_low_slip`, and `maker_zero_fee_low_slip` are sensitivity-only until real account fee evidence exists.
- `zero_cost_theoretical` is never acceptance evidence.
- Lower fees cannot be used to manufacture high winrate, positive expectancy, or paper/live readiness.

## Optional Fee-Tier Evidence Artifact

If real account fee tiers are later available, store only non-secret values:

```json
{
  "mode": "funding_account_fee_tiers",
  "accepted": true,
  "evidence_date": "YYYY-MM-DD",
  "source": "account_ui_or_exchange_fee_page_no_secrets",
  "exchanges": {
    "mexc": {
      "spot_maker_fee_bps": 0.0,
      "spot_taker_fee_bps": 0.0,
      "perp_maker_fee_bps": 0.0,
      "perp_taker_fee_bps": 0.0
    },
    "gateio": {
      "spot_maker_fee_bps": 0.0,
      "spot_taker_fee_bps": 0.0,
      "perp_maker_fee_bps": 0.0,
      "perp_taker_fee_bps": 0.0
    }
  }
}
```

Default expected path:

```text
C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\analysis\funding_account_fee_tiers_current.json
```

Template path:

```text
C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\analysis\funding_account_fee_tiers_template.json
```

Do not put API keys, account IDs, balances, emails, cookies, screenshots with personal data, or withdrawal details in this artifact.
