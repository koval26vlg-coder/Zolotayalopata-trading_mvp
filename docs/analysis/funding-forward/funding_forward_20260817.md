# Funding forward snapshot 20260817

Run: `daily_forward_20260817` (top=200, days=200), collector_exit=0, pairs_exit=0, gate_exit=0, audit_exit=0, history_exit=0
Artifacts: `exports/trading-mvp/daily/daily_forward_20260817/manifest.json`, `exports/trading-mvp/analysis/funding_pairs_forward_20260817.json`, `exports/trading-mvp/analysis/execution_gate_forward_20260817.json`, `exports/trading-mvp/analysis/funding_forward_audit_20260817.json`, `exports/trading-mvp/analysis/funding_forward_history_audit_20260817.json`
Universe: `C:\Users\koval\Documents\ZolotyayLopata\coins_not_on_binance_full_2026-05-29.csv` (explicitly pinned; this runner does not migrate the universe snapshot)

## Funding pairs

```text
shared symbols: 24, analyzed pairs: 24
top-15 by |annualized spread|:
  H_USDT               spread=   49.70%/y cons=0.23 days=91 legs(mexc/gate)=-253.88/-204.18% basis_std=156.68bps spot=True minVol24h=$15,255,876
  AKE_USDT             spread=  -28.77%/y cons=0.88 days=91 legs(mexc/gate)=22.27/-6.51% basis_std=17.78bps spot=True minVol24h=$19,977,771
  EVAA_USDT            spread=  -17.42%/y cons=0.80 days=91 legs(mexc/gate)=31.74/14.32% basis_std=17.23bps spot=True minVol24h=$400,070
  LIGHT_USDT           spread=  -13.31%/y cons=0.71 days=91 legs(mexc/gate)=24.9/11.59% basis_std=16.83bps spot=True minVol24h=$620,710
  BR_USDT              spread=  -12.84%/y cons=0.77 days=91 legs(mexc/gate)=23.37/10.53% basis_std=21.77bps spot=True minVol24h=$653,881
  AIO_USDT             spread=   12.72%/y cons=0.54 days=91 legs(mexc/gate)=15.2/27.92% basis_std=29.63bps spot=True minVol24h=$6,842,670
  BLESS_USDT           spread=   -9.20%/y cons=0.68 days=91 legs(mexc/gate)=24.98/15.78% basis_std=14.76bps spot=True minVol24h=$1,610,343
  VELVET_USDT          spread=   -9.19%/y cons=0.69 days=91 legs(mexc/gate)=14.25/5.06% basis_std=27.19bps spot=True minVol24h=$13,811,906
  CYS_USDT             spread=   -8.92%/y cons=0.69 days=91 legs(mexc/gate)=9.28/0.35% basis_std=30.15bps spot=True minVol24h=$28,493,618
  LAB_USDT             spread=    8.08%/y cons=0.34 days=91 legs(mexc/gate)=-673.58/-665.5% basis_std=37.37bps spot=True minVol24h=$1,502,583
  FARTCOIN_USDT        spread=   -7.93%/y cons=0.82 days=91 legs(mexc/gate)=15.37/7.44% basis_std=7.2bps spot=True minVol24h=$3,617,788
  LIT_USDT             spread=   -7.51%/y cons=0.79 days=91 legs(mexc/gate)=7.59/0.09% basis_std=9.27bps spot=True minVol24h=$1,858,725
  TAG_USDT             spread=   -7.33%/y cons=0.49 days=91 legs(mexc/gate)=18.79/11.46% basis_std=20.72bps spot=True minVol24h=$389,494
  APR_USDT             spread=    5.94%/y cons=0.51 days=91 legs(mexc/gate)=28.52/34.46% basis_std=23.16bps spot=True minVol24h=$5,558,214
  PI_USDT              spread=    4.58%/y cons=0.45 days=91 legs(mexc/gate)=-6.49/-1.91% basis_std=10.73bps spot=True minVol24h=$1,038,127
DONE report=C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\analysis\funding_pairs_forward_20260817.json
```

## Execution gate (стаканы watchlist)

```text
auto-selected candidates: 9
BTW_USDT           E: cap=$1,572 net=68.49%/y ($1,077)  G: cap=$1,434 net=-5.71%/y errors=0
BSB_USDT           E: cap=$822 net=23.3%/y ($191)  G: cap=$1,875 net=-7.47%/y errors=0
EVAA_USDT          E: cap=$413 net=22.93%/y ($95)  G: cap=$969 net=9.83%/y errors=0
APR_USDT           E: cap=$445 net=20.39%/y ($91)  G: cap=$797 net=-1.5%/y errors=0
BLESS_USDT         E: cap=$1,504 net=15.52%/y ($233)  G: cap=$644 net=1.75%/y errors=0
LIGHT_USDT         E: cap=$42 net=13.42%/y ($6)  G: cap=$190 net=5.74%/y errors=0
SKYAI_USDT         E: cap=$813 net=14.79%/y ($120)  G: cap=$1,424 net=-7.2%/y errors=0
BR_USDT            E: cap=$0 net=6.14%/y ($0)  G: cap=$519 net=2.61%/y errors=0
AKE_USDT           E: cap=$809 net=14.05%/y ($114)  G: cap=$901 net=21.4%/y errors=0
DONE report=C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\analysis\execution_gate_forward_20260817.json
```

## Deterministic offline audit

```text
AUDIT decision=WATCHLIST_ONLY_NOT_EDGE_EVIDENCE passed=true acceptance_allowed=false hash=1b65a02eefb7c6043a11a6b203cef51719eb30da4c1c0390fbcc957515ebbd2f out=C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\analysis\funding_forward_audit_20260817.json
```

## Longitudinal overlap audit

```text
HISTORY_AUDIT decision=OVERLAPPING_SUMMARIES_NOT_INDEPENDENT_EDGE_EVIDENCE passed=true comparable=4 first_last_overlap_days=63 independent_holdouts=0 hash=143d038481490596cc6323fc7765b4f63fd47ce3ed931fcc149d60d1649ed03e out=C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\analysis\funding_forward_history_audit_20260817.json
```

## Interpretation limits

- Decision is watchlist-only, never edge acceptance.
- The universe is selected by current 24h volume and then backfilled historically; it is not point-in-time.
- Ticker equality is not asset identity. Only same-contract exchange evidence is marked verified.
- Order-book capacity is one snapshot, not time-averaged executable capacity.
- Annualized funding minus modeled costs is not realized return or PnL.
- Chronological OOS, walk-forward and stress gates are not run by this task.
