import pandas as pd, numpy as np, math, json
fr = pd.read_csv("fred_dl/DTB3.csv"); fr.columns=["date","d"]; fr["date"]=pd.to_datetime(fr["date"]); fr["d"]=pd.to_numeric(fr["d"],errors="coerce")
obs = fr.dropna().set_index("date")["d"]/100
def rate_before(t):
    s = obs[obs.index <= (t.normalize() - pd.Timedelta(days=1))]; return s.iloc[-1]
def qroll(t0, t1):
    t0=pd.Timestamp(t0).tz_localize(None); t1=pd.Timestamp(t1).tz_localize(None)
    g=1.0; t=t0
    while t < t1:
        d = rate_before(t); m = min(t + pd.Timedelta(days=91), t1)
        days = (m - t)/pd.Timedelta(days=1)
        full = 1/(1 - d*91/360) - 1
        g *= 1 + full*days/91      # linear within an unfinished bill (pro-rata)
        t = m
    return g
for nm,t0,t1,base,cg in [("C1_OOS","2023-01-01","2026-10-07",365.25,3.168081480495699),
                        ("C16","2023-02-06 23:01:24.670","2026-10-06 23:01:10.597",365.0,4.65620038450687),
                        ("C11_OOS","2023-01-02 08:00","2026-10-05 08:00",365.25,25.46)]:
    yrs=(pd.Timestamp(t1)-pd.Timestamp(t0))/pd.Timedelta(days=base)
    tb=(qroll(t0,t1)**(1/yrs)-1)*100
    print(nm, "qroll TB CAGR=%.3f excess=%.3f"%(tb, cg-tb))
r=json.load(open("repro/C1/result.json"))["results"]["FULL"]
print("C1 calendar years:", {k: round(v,2) for k,v in r["calendar_year_return_pct"].items()})
print("C1 per asset FULL:", {s:{k:round(v,2) if isinstance(v,float) else v for k,v in d.items()} for s,d in r["per_asset"].items()})
