# Funding forward snapshot 20260803

Run: `daily_forward_20260803` (top=200, days=200), collector_exit=0, pairs_exit=0, gate_exit=0
Artifacts: `exports/trading-mvp/daily/daily_forward_20260803/manifest.json`, `exports/trading-mvp/analysis/funding_pairs_forward_20260803.json`, `exports/trading-mvp/analysis/execution_gate_forward_20260803.json`

## Funding pairs

```text
shared symbols: 26, analyzed pairs: 26
top-15 by |annualized spread|:
  H_USDT               spread=   51.00%/y cons=0.23 days=91 legs(mexc/gate)=-255.2/-204.2% basis_std=156.22bps spot=True minVol24h=$985,231
  AKE_USDT             spread=  -28.07%/y cons=0.89 days=91 legs(mexc/gate)=24.3/-3.76% basis_std=28.42bps spot=True minVol24h=$25,846,587
  ESPORTS_USDT         spread=  -26.34%/y cons=0.45 days=91 legs(mexc/gate)=65.7/39.36% basis_std=228.53bps spot=True minVol24h=$1,372,394
  LAB_USDT             spread=   20.37%/y cons=0.47 days=91 legs(mexc/gate)=-672.39/-652.02% basis_std=37.38bps spot=True minVol24h=$1,470,029
  EVAA_USDT            spread=  -19.48%/y cons=0.80 days=91 legs(mexc/gate)=35.47/15.99% basis_std=20.44bps spot=True minVol24h=$1,027,302
  SLX_USDT             spread=  -15.77%/y cons=0.47 days=70 legs(mexc/gate)=-264.65/-283.99% basis_std=26.52bps spot=True minVol24h=$845,537
  AIO_USDT             spread=   14.83%/y cons=0.52 days=91 legs(mexc/gate)=12.66/27.49% basis_std=35.3bps spot=True minVol24h=$990,867
  PIEVERSE_USDT        spread=  -13.77%/y cons=0.82 days=91 legs(mexc/gate)=25.0/11.23% basis_std=14.77bps spot=True minVol24h=$1,311,645
  BTW_USDT             spread=   12.21%/y cons=0.61 days=61 legs(mexc/gate)=49.78/67.88% basis_std=22.47bps spot=True minVol24h=$5,568,702
  SKYAI_USDT           spread=   10.96%/y cons=0.36 days=91 legs(mexc/gate)=27.46/38.42% basis_std=16.28bps spot=True minVol24h=$2,027,815
  LIT_USDT             spread=   -7.49%/y cons=0.75 days=91 legs(mexc/gate)=7.93/0.44% basis_std=10.55bps spot=True minVol24h=$1,326,027
  UB_USDT              spread=   -7.35%/y cons=0.79 days=91 legs(mexc/gate)=15.85/8.5% basis_std=15.12bps spot=True minVol24h=$3,372,052
  BLESS_USDT           spread=   -6.18%/y cons=0.60 days=91 legs(mexc/gate)=26.65/20.46% basis_std=24.7bps spot=True minVol24h=$50,336,704
  BILL_USDT            spread=    6.00%/y cons=0.49 days=89 legs(mexc/gate)=11.15/16.78% basis_std=13.93bps spot=True minVol24h=$395,471
  FARTCOIN_USDT        spread=   -5.34%/y cons=0.74 days=91 legs(mexc/gate)=12.67/7.32% basis_std=6.12bps spot=True minVol24h=$2,469,593
DONE report=C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\analysis\funding_pairs_forward_20260803.json
```

## Execution gate (стаканы watchlist)

```text
auto-selected candidates: 8
BULLA_USDT         E: cap=$332 net=61.9%/y ($205)  G: cap=$550 net=-8.16%/y errors=0
ESPORTS_USDT       E: cap=$1 net=50.66%/y ($0)  G: cap=$646 net=18.21%/y errors=0
BTW_USDT           E: cap=$1,242 net=41.4%/y ($514)  G: cap=$1,274 net=3.71%/y errors=0
EVAA_USDT          E: cap=$337 net=25.94%/y ($87)  G: cap=$882 net=11.73%/y errors=0
SKYAI_USDT         E: cap=$993 net=17.25%/y ($171)  G: cap=$811 net=1.31%/y errors=0
BLESS_USDT         E: cap=$263 net=17.0%/y ($45)  G: cap=$2,075 net=-1.37%/y errors=0
PIEVERSE_USDT      E: cap=$654 net=16.46%/y ($108)  G: cap=$2,455 net=5.91%/y errors=0
AKE_USDT           E: cap=$858 net=15.79%/y ($135)  G: cap=$1,942 net=20.43%/y errors=0
DONE report=C:\Users\koval\Documents\ZolotyayLopata\exports\trading-mvp\analysis\execution_gate_forward_20260803.json
```
