# Funding forward snapshot 20260706

Run: `daily_forward_20260706` (top=200, days=200), collector_exit=1, pairs_exit=0, gate_exit=0
Artifacts: `exports/trading-mvp/daily/daily_forward_20260706/manifest.json`, `exports/trading-mvp/analysis/funding_pairs_forward_20260706.json`, `exports/trading-mvp/analysis/execution_gate_forward_20260706.json`

## Funding pairs

```text
shared symbols: 132, analyzed pairs: 121
top-15 by |annualized spread|:
  RAVE_USDT            spread=   90.97%/y cons=0.85 days=91 legs(mexc/gate)=-190.53/-99.57% basis_std=105.81bps spot=True minVol24h=$665,394
  H_USDT               spread=   49.77%/y cons=0.22 days=91 legs(mexc/gate)=-253.89/-204.11% basis_std=156.06bps spot=True minVol24h=$1,742,255
  SLX_USDT             spread=  -47.78%/y cons=0.55 days=42 legs(mexc/gate)=-295.92/-350.4% basis_std=32.67bps spot=True minVol24h=$7,911,919
  LAB_USDT             spread=   41.81%/y cons=0.59 days=91 legs(mexc/gate)=-505.75/-463.95% basis_std=35.37bps spot=True minVol24h=$57,722,297
  ESPORTS_USDT         spread=  -34.93%/y cons=0.36 days=91 legs(mexc/gate)=60.94/26.01% basis_std=229.19bps spot=True minVol24h=$676,264
  BEAT_USDT            spread=  -24.65%/y cons=0.79 days=91 legs(mexc/gate)=55.7/31.05% basis_std=21.55bps spot=True minVol24h=$3,592,790
  AIGENSYN_USDT        spread=   24.41%/y cons=0.61 days=69 legs(mexc/gate)=-55.83/-31.42% basis_std=22.49bps spot=False minVol24h=$1,658,221
  EWY_USDT             spread=   24.08%/y cons=0.78 days=91 legs(mexc/gate)=-5.03/19.05% basis_std=21.97bps spot=False minVol24h=$2,014,399
  4_USDT               spread=   22.71%/y cons=0.61 days=91 legs(mexc/gate)=29.58/52.29% basis_std=22.73bps spot=True minVol24h=$2,442,484
  MAGMA_USDT           spread=  -20.52%/y cons=0.69 days=91 legs(mexc/gate)=36.67/16.15% basis_std=28.09bps spot=True minVol24h=$1,275,168
  GIGGLE_USDT          spread=  -18.75%/y cons=0.99 days=91 legs(mexc/gate)=22.58/3.82% basis_std=23.87bps spot=True minVol24h=$1,165,975
  B_USDT               spread=  -17.95%/y cons=0.68 days=91 legs(mexc/gate)=40.3/22.35% basis_std=14.79bps spot=True minVol24h=$932,170
  EPIC_USDT            spread=   17.59%/y cons=0.69 days=91 legs(mexc/gate)=7.56/25.16% basis_std=78.14bps spot=True minVol24h=$4,279,566
  PIPPIN_USDT          spread=  -15.17%/y cons=0.78 days=91 legs(mexc/gate)=41.24/26.07% basis_std=22.99bps spot=True minVol24h=$398,428
  UB_USDT              spread=  -14.92%/y cons=0.76 days=91 legs(mexc/gate)=28.13/13.21% basis_std=17.24bps spot=True minVol24h=$1,743,114
DONE report=C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\analysis\funding_pairs_forward_20260706.json
```

## Execution gate (стаканы watchlist)

```text
auto-selected candidates: 11
SKYAI_USDT         E: cap=$820 net=30.54%/y ($250)  G: cap=$1,685 net=3.97%/y errors=0
ESPORTS_USDT       E: cap=$9 net=22.84%/y ($2)  G: cap=$742 net=15.3%/y errors=0
BEAT_USDT          E: cap=$1,416 net=26.66%/y ($378)  G: cap=$4,880 net=10.86%/y errors=0
PIPPIN_USDT        E: cap=$514 net=17.91%/y ($92)  G: cap=$293 net=0.66%/y errors=0
TAC_USDT           E: cap=$680 net=17.83%/y ($121)  G: cap=$1,136 net=1.98%/y errors=0
BAS_USDT           E: cap=$14 net=8.94%/y ($1)  G: cap=$570 net=3.78%/y errors=0
B_USDT             E: cap=$785 net=16.77%/y ($132)  G: cap=$731 net=6.34%/y errors=0
BSB_USDT           E: cap=$1,631 net=15.92%/y ($260)  G: cap=$1,109 net=0.33%/y errors=0
RAVE_USDT          E: cap=$0 net=17.92%/y ($0)  G: cap=$1,409 net=44.22%/y errors=0
EWY_USDT           E: cap=$0 net=-%/y ($0)  G: cap=$10,072 net=11.79%/y errors=1
GIGGLE_USDT        E: cap=$1,414 net=10.0%/y ($141)  G: cap=$1,426 net=7.66%/y errors=0
DONE report=C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\analysis\execution_gate_forward_20260706.json
```
