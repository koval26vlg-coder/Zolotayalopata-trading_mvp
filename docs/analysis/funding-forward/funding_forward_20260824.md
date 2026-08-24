# Funding forward snapshot 20260824

Run: `daily_forward_20260824` (top=200, days=200), collector_exit=0, pairs_exit=0, gate_exit=0, audit_exit=0, history_exit=0
Artifacts: `exports/trading-mvp/daily/daily_forward_20260824/manifest.json`, `exports/trading-mvp/analysis/funding_pairs_forward_20260824.json`, `exports/trading-mvp/analysis/execution_gate_forward_20260824.json`, `exports/trading-mvp/analysis/funding_forward_audit_20260824.json`, `exports/trading-mvp/analysis/funding_forward_history_audit_20260824.json`
Universe: `C:\Users\koval\Documents\ZolotyayLopata\coins_not_on_binance_full_2026-05-29.csv` (explicitly pinned; this runner does not migrate the universe snapshot)

## Funding pairs

```text
shared symbols: 20, analyzed pairs: 20
top-15 by |annualized spread|:
  H_USDT               spread=   51.27%/y cons=0.23 days=91 legs(mexc/gate)=-254.89/-203.62% basis_std=156.48bps spot=True minVol24h=$1,149,044
  AKE_USDT             spread=  -29.57%/y cons=0.90 days=91 legs(mexc/gate)=23.26/-6.31% basis_std=17.25bps spot=True minVol24h=$2,554,502
  VELVET_USDT          spread=  -10.30%/y cons=0.75 days=91 legs(mexc/gate)=14.49/4.19% basis_std=21.19bps spot=True minVol24h=$1,044,714
  CYS_USDT             spread=   -9.61%/y cons=0.74 days=91 legs(mexc/gate)=10.1/0.49% basis_std=28.41bps spot=True minVol24h=$1,343,863
  BLESS_USDT           spread=   -9.43%/y cons=0.68 days=91 legs(mexc/gate)=25.26/15.83% basis_std=15.78bps spot=True minVol24h=$1,880,885
  FARTCOIN_USDT        spread=   -9.32%/y cons=0.83 days=91 legs(mexc/gate)=17.18/7.86% basis_std=13.47bps spot=True minVol24h=$9,033,914
  LIT_USDT             spread=   -6.42%/y cons=0.76 days=91 legs(mexc/gate)=7.08/0.67% basis_std=8.99bps spot=True minVol24h=$10,782,804
  USELESS_USDT         spread=   -6.26%/y cons=0.65 days=91 legs(mexc/gate)=15.49/9.23% basis_std=13.68bps spot=True minVol24h=$729,297
  GRASS_USDT           spread=   -5.66%/y cons=0.71 days=91 legs(mexc/gate)=11.06/5.4% basis_std=15.08bps spot=True minVol24h=$1,482,413
  PI_USDT              spread=    5.21%/y cons=0.45 days=91 legs(mexc/gate)=-5.54/-0.33% basis_std=11.78bps spot=True minVol24h=$1,983,561
  UAI_USDT             spread=   -5.00%/y cons=0.35 days=91 legs(mexc/gate)=15.86/10.86% basis_std=17.2bps spot=True minVol24h=$5,773,634
  LAB_USDT             spread=    4.70%/y cons=0.26 days=91 legs(mexc/gate)=-672.45/-667.75% basis_std=37.09bps spot=True minVol24h=$1,263,008
  KAS_USDT             spread=   -4.28%/y cons=0.65 days=91 legs(mexc/gate)=8.05/3.77% basis_std=9.79bps spot=True minVol24h=$575,427
  GRAM_USDT            spread=    3.92%/y cons=0.53 days=70 legs(mexc/gate)=-0.85/2.84% basis_std=18.82bps spot=True minVol24h=$2,318,708
  ZORA_USDT            spread=    3.64%/y cons=0.40 days=91 legs(mexc/gate)=-6.32/-2.68% basis_std=24.2bps spot=True minVol24h=$734,447
DONE report=C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\analysis\funding_pairs_forward_20260824.json
```

## Execution gate (стаканы watchlist)

```text
auto-selected candidates: 4
BTW_USDT           E: cap=$1,456 net=70.98%/y ($1,033)  G: cap=$2,692 net=-6.83%/y errors=0
BLESS_USDT         E: cap=$715 net=15.78%/y ($113)  G: cap=$1,325 net=1.84%/y errors=0
SKYAI_USDT         E: cap=$845 net=16.39%/y ($138)  G: cap=$712 net=-6.93%/y errors=0
AKE_USDT           E: cap=$565 net=15.12%/y ($85)  G: cap=$803 net=22.78%/y errors=0
DONE report=C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\analysis\execution_gate_forward_20260824.json
```

## Deterministic offline audit

```text
AUDIT decision=WATCHLIST_ONLY_NOT_EDGE_EVIDENCE passed=true acceptance_allowed=false hash=68cc6c6cad8d1b8b5dba18c4ea119b1c87cc8c6e89aa31a0cc126b7ffadd5700 out=C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\analysis\funding_forward_audit_20260824.json
```

## Longitudinal overlap audit

```text
HISTORY_AUDIT decision=OVERLAPPING_SUMMARIES_NOT_INDEPENDENT_EDGE_EVIDENCE passed=true comparable=5 first_last_overlap_days=56 independent_holdouts=0 hash=a207bfff835240b87e5eddc60807e6d65a0ac1a93436ebbd6584064333ebed9a out=C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\analysis\funding_forward_history_audit_20260824.json
```

## Interpretation limits

- Decision is watchlist-only, never edge acceptance.
- The universe is selected by current 24h volume and then backfilled historically; it is not point-in-time.
- Ticker equality is not asset identity. Only same-contract exchange evidence is marked verified.
- Order-book capacity is one snapshot, not time-averaged executable capacity.
- Annualized funding minus modeled costs is not realized return or PnL.
- Chronological OOS, walk-forward and stress gates are not run by this task.
