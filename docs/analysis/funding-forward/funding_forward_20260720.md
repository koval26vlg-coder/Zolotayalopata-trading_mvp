# Funding forward snapshot 20260720

Run: `daily_forward_20260720` (top=200, days=200), collector_exit=0, pairs_exit=0, gate_exit=0
Artifacts: `exports/trading-mvp/daily/daily_forward_20260720/manifest.json`, `exports/trading-mvp/analysis/funding_pairs_forward_20260720.json`, `exports/trading-mvp/analysis/execution_gate_forward_20260720.json`

## Funding pairs

```text
shared symbols: 30, analyzed pairs: 29
top-15 by |annualized spread|:
  RAVE_USDT            spread=   57.49%/y cons=0.82 days=91 legs(mexc/gate)=32.31/89.81% basis_std=11.68bps spot=True minVol24h=$498,708
  H_USDT               spread=   44.32%/y cons=0.23 days=91 legs(mexc/gate)=-248.71/-204.4% basis_std=155.87bps spot=True minVol24h=$586,409
  ESPORTS_USDT         spread=  -31.53%/y cons=0.42 days=91 legs(mexc/gate)=54.31/22.78% basis_std=228.95bps spot=True minVol24h=$35,656,522
  LAB_USDT             spread=   30.17%/y cons=0.54 days=91 legs(mexc/gate)=-659.4/-629.22% basis_std=37.85bps spot=True minVol24h=$6,392,013
  AKE_USDT             spread=  -29.75%/y cons=0.88 days=91 legs(mexc/gate)=46.66/16.91% basis_std=22.83bps spot=True minVol24h=$32,944,210
  EVAA_USDT            spread=  -28.95%/y cons=0.81 days=91 legs(mexc/gate)=45.38/16.42% basis_std=23.38bps spot=True minVol24h=$3,100,120
  B_USDT               spread=  -21.49%/y cons=0.76 days=91 legs(mexc/gate)=41.8/20.31% basis_std=14.16bps spot=True minVol24h=$24,466,392
  SLX_USDT             spread=  -20.04%/y cons=0.45 days=56 legs(mexc/gate)=-315.32/-340.74% basis_std=28.45bps spot=True minVol24h=$1,114,584
  SKYAI_USDT           spread=   15.62%/y cons=0.45 days=91 legs(mexc/gate)=42.32/57.94% basis_std=14.86bps spot=True minVol24h=$897,044
  BLESS_USDT           spread=  -11.93%/y cons=0.65 days=91 legs(mexc/gate)=29.34/17.4% basis_std=19.16bps spot=True minVol24h=$478,657
  BTW_USDT             spread=   10.19%/y cons=0.57 days=47 legs(mexc/gate)=38.93/65.19% basis_std=14.75bps spot=True minVol24h=$720,284
  GRASS_USDT           spread=  -10.02%/y cons=0.66 days=91 legs(mexc/gate)=11.28/1.25% basis_std=15.89bps spot=True minVol24h=$359,483
  UB_USDT              spread=   -9.82%/y cons=0.72 days=91 legs(mexc/gate)=20.07/10.25% basis_std=16.15bps spot=True minVol24h=$498,822
  BULLA_USDT           spread=   -9.33%/y cons=0.58 days=91 legs(mexc/gate)=80.27/70.94% basis_std=21.9bps spot=True minVol24h=$686,477
  ZEREBRO_USDT         spread=   -8.42%/y cons=0.64 days=91 legs(mexc/gate)=11.46/3.04% basis_std=26.39bps spot=True minVol24h=$845,392
DONE report=C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\analysis\funding_pairs_forward_20260720.json
```

## Execution gate (стаканы watchlist)

```text
auto-selected candidates: 8
BULLA_USDT         E: cap=$9 net=68.87%/y ($6)  G: cap=$398 net=0.39%/y errors=0
ESPORTS_USDT       E: cap=$0 net=33.5%/y ($0)  G: cap=$510 net=24.07%/y errors=0
AKE_USDT           E: cap=$474 net=37.18%/y ($176)  G: cap=$1,672 net=21.9%/y errors=0
EVAA_USDT          E: cap=$424 net=36.67%/y ($156)  G: cap=$1,416 net=21.25%/y errors=0
SKYAI_USDT         E: cap=$876 net=33.77%/y ($296)  G: cap=$520 net=8.05%/y errors=0
B_USDT             E: cap=$1,074 net=32.69%/y ($351)  G: cap=$1,669 net=12.9%/y errors=0
BTW_USDT           E: cap=$909 net=30.06%/y ($273)  G: cap=$1,161 net=0.88%/y errors=0
RAVE_USDT          E: cap=$0 net=-0.31%/y ($-0)  G: cap=$1,452 net=49.92%/y errors=0
DONE report=C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\analysis\execution_gate_forward_20260720.json
```
