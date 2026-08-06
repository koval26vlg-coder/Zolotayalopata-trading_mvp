# Funding forward snapshot 20260713

Run: `daily_forward_20260713` (top=200, days=200), collector_exit=0, pairs_exit=0, gate_exit=0
Artifacts: `exports/trading-mvp/daily/daily_forward_20260713/manifest.json`, `exports/trading-mvp/analysis/funding_pairs_forward_20260713.json`, `exports/trading-mvp/analysis/execution_gate_forward_20260713.json`

## Funding pairs

```text
shared symbols: 119, analyzed pairs: 113
top-15 by |annualized spread|:
  RAVE_USDT            spread=   56.26%/y cons=0.86 days=91 legs(mexc/gate)=-118.05/-61.78% basis_std=53.86bps spot=True minVol24h=$411,762
  H_USDT               spread=   47.30%/y cons=0.22 days=91 legs(mexc/gate)=-251.48/-204.18% basis_std=155.9bps spot=True minVol24h=$1,272,250
  EVAA_USDT            spread=  -32.80%/y cons=0.85 days=91 legs(mexc/gate)=49.1/16.31% basis_std=24.2bps spot=True minVol24h=$23,676,928
  LAB_USDT             spread=   32.29%/y cons=0.56 days=91 legs(mexc/gate)=-658.91/-626.62% basis_std=36.07bps spot=True minVol24h=$11,323,691
  SLX_USDT             spread=  -26.91%/y cons=0.49 days=49 legs(mexc/gate)=-347.16/-380.85% basis_std=30.1bps spot=True minVol24h=$1,216,101
  VANRY_USDT           spread=  -22.52%/y cons=0.51 days=91 legs(mexc/gate)=-45.6/-68.12% basis_std=20.37bps spot=True minVol24h=$3,347,970
  AIOT_USDT            spread=  -22.00%/y cons=0.75 days=91 legs(mexc/gate)=36.98/14.98% basis_std=39.62bps spot=True minVol24h=$553,102
  B_USDT               spread=  -19.94%/y cons=0.72 days=91 legs(mexc/gate)=40.84/20.9% basis_std=14.2bps spot=True minVol24h=$4,832,999
  BEAT_USDT            spread=  -19.45%/y cons=0.76 days=91 legs(mexc/gate)=48.69/29.23% basis_std=16.61bps spot=True minVol24h=$14,365,894
  MAGMA_USDT           spread=  -18.01%/y cons=0.68 days=91 legs(mexc/gate)=33.65/15.63% basis_std=27.39bps spot=True minVol24h=$4,118,715
  PIPPIN_USDT          spread=  -16.42%/y cons=0.80 days=91 legs(mexc/gate)=39.33/22.91% basis_std=23.39bps spot=True minVol24h=$835,724
  T_USDT               spread=  -16.16%/y cons=0.74 days=91 legs(mexc/gate)=-69.1/-85.27% basis_std=30.74bps spot=True minVol24h=$17,210,022
  OPG_USDT             spread=  -14.82%/y cons=0.34 days=84 legs(mexc/gate)=-19.34/-34.16% basis_std=29.83bps spot=True minVol24h=$360,562
  NIL_USDT             spread=  -14.34%/y cons=0.66 days=91 legs(mexc/gate)=4.83/-9.51% basis_std=11.61bps spot=True minVol24h=$268,478
  EWY_USDT             spread=   14.14%/y cons=0.72 days=91 legs(mexc/gate)=6.18/20.31% basis_std=15.43bps spot=False minVol24h=$2,333,227
DONE report=C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\analysis\funding_pairs_forward_20260713.json
```

## Execution gate (стаканы watchlist)

```text
auto-selected candidates: 9
SKYAI_USDT         E: cap=$1,286 net=26.58%/y ($342)  G: cap=$1,779 net=3.52%/y errors=0
CLO_USDT           E: cap=$398 net=22.26%/y ($89)  G: cap=$700 net=1.89%/y errors=0
EVAA_USDT          E: cap=$83 net=22.29%/y ($18)  G: cap=$1,313 net=15.27%/y errors=0
BEAT_USDT          E: cap=$1,209 net=23.39%/y ($283)  G: cap=$1,754 net=8.42%/y errors=0
B_USDT             E: cap=$636 net=19.06%/y ($121)  G: cap=$732 net=6.57%/y errors=0
US_USDT            E: cap=$1,012 net=17.14%/y ($173)  G: cap=$1,573 net=5.13%/y errors=0
PIPPIN_USDT        E: cap=$663 net=15.04%/y ($100)  G: cap=$396 net=0.38%/y errors=0
BSB_USDT           E: cap=$2,622 net=15.38%/y ($403)  G: cap=$738 net=-0.11%/y errors=0
RAVE_USDT          E: cap=$0 net=29.65%/y ($0)  G: cap=$2,059 net=26.7%/y errors=0
DONE report=C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\analysis\execution_gate_forward_20260713.json
```
