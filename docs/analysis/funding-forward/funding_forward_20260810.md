# Funding forward snapshot 20260810

Run: `daily_forward_20260810` (top=200, days=200), collector_exit=0, pairs_exit=0, gate_exit=0
Artifacts: `exports/trading-mvp/daily/daily_forward_20260810/manifest.json`, `exports/trading-mvp/analysis/funding_pairs_forward_20260810.json`, `exports/trading-mvp/analysis/execution_gate_forward_20260810.json`

## Funding pairs

```text
shared symbols: 31, analyzed pairs: 31
top-15 by |annualized spread|:
  AKE_USDT             spread=  -29.68%/y cons=0.90 days=91 legs(mexc/gate)=23.36/-6.32% basis_std=17.46bps spot=True minVol24h=$3,931,595
  ESPORTS_USDT         spread=  -23.84%/y cons=0.46 days=91 legs(mexc/gate)=76.38/52.54% basis_std=227.48bps spot=True minVol24h=$1,325,030
  RAVE_USDT            spread=   21.06%/y cons=0.79 days=91 legs(mexc/gate)=28.53/49.59% basis_std=9.5bps spot=True minVol24h=$901,514
  4_USDT               spread=   17.61%/y cons=0.63 days=91 legs(mexc/gate)=27.3/44.91% basis_std=21.93bps spot=True minVol24h=$719,376
  BLUAI_USDT           spread=  -17.04%/y cons=0.76 days=91 legs(mexc/gate)=31.02/13.98% basis_std=47.17bps spot=True minVol24h=$2,572,920
  EVAA_USDT            spread=  -16.62%/y cons=0.79 days=91 legs(mexc/gate)=30.93/14.32% basis_std=18.15bps spot=True minVol24h=$990,738
  INX_USDT             spread=   14.93%/y cons=0.66 days=91 legs(mexc/gate)=13.7/28.63% basis_std=21.33bps spot=True minVol24h=$689,048
  LAB_USDT             spread=   14.05%/y cons=0.42 days=91 legs(mexc/gate)=-675.78/-661.73% basis_std=37.27bps spot=True minVol24h=$1,446,465
  SLX_USDT             spread=  -12.67%/y cons=0.44 days=77 legs(mexc/gate)=-242.47/-258.09% basis_std=25.41bps spot=True minVol24h=$817,811
  UB_USDT              spread=   -8.89%/y cons=0.78 days=91 legs(mexc/gate)=13.29/4.4% basis_std=15.03bps spot=True minVol24h=$1,094,450
  BTW_USDT             spread=    7.97%/y cons=0.56 days=68 legs(mexc/gate)=65.97/73.94% basis_std=15.35bps spot=True minVol24h=$7,159,252
  LIT_USDT             spread=   -7.90%/y cons=0.78 days=91 legs(mexc/gate)=7.93/0.03% basis_std=9.59bps spot=True minVol24h=$2,047,967
  ON_USDT              spread=   -7.89%/y cons=0.26 days=91 legs(mexc/gate)=20.53/12.64% basis_std=41.67bps spot=True minVol24h=$1,541,186
  BSV_USDT             spread=    7.71%/y cons=0.40 days=91 legs(mexc/gate)=-7.29/0.42% basis_std=14.21bps spot=True minVol24h=$667,052
  FARTCOIN_USDT        spread=   -7.53%/y cons=0.81 days=91 legs(mexc/gate)=14.81/7.28% basis_std=7.21bps spot=True minVol24h=$4,576,901
DONE report=C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\analysis\funding_pairs_forward_20260810.json
```

## Execution gate (стаканы watchlist)

```text
auto-selected candidates: 9
ESPORTS_USDT       E: cap=$3 net=63.71%/y ($2)  G: cap=$1,288 net=15.69%/y errors=0
BTW_USDT           E: cap=$556 net=55.54%/y ($309)  G: cap=$1,808 net=-2.8%/y errors=0
BLUAI_USDT         E: cap=$479 net=20.91%/y ($100)  G: cap=$247 net=8.57%/y errors=0
EVAA_USDT          E: cap=$144 net=22.54%/y ($32)  G: cap=$840 net=9.18%/y errors=0
RAVE_USDT          E: cap=$0 net=-129.89%/y ($-0)  G: cap=$1,366 net=13.35%/y errors=0
4_USDT             E: cap=$654 net=16.59%/y ($109)  G: cap=$266 net=8.73%/y errors=0
BLESS_USDT         E: cap=$1,686 net=16.08%/y ($271)  G: cap=$2,035 net=-0.23%/y errors=0
SKYAI_USDT         E: cap=$1,149 net=15.37%/y ($177)  G: cap=$445 net=-4.37%/y errors=0
AKE_USDT           E: cap=$613 net=14.69%/y ($90)  G: cap=$2,230 net=22.81%/y errors=0
DONE report=C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\analysis\execution_gate_forward_20260810.json
```
