import json, math, sys
C = sys.argv[1]; V = sys.argv[2]
def walk(a, b, path, acc):
    if isinstance(a, dict) and isinstance(b, dict):
        for k in a:
            if k in ("file", "sha256"):  # paths differ by sandbox
                continue
            if k not in b: acc['missing'].append(path+'/'+str(k)); continue
            walk(a[k], b[k], path+'/'+str(k), acc)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b): acc['lenmis'].append((path, len(a), len(b)))
        for i,(x,y) in enumerate(zip(a,b)): walk(x,y,path+f'[{i}]',acc)
    elif isinstance(a,(int,float)) and not isinstance(a,bool) and isinstance(b,(int,float)) and not isinstance(b,bool):
        acc['n'] += 1
        if (isinstance(a,float) and math.isnan(a)) and (isinstance(b,float) and math.isnan(b)): return
        d = abs(a-b); rel = d/abs(a) if a != 0 else d
        acc['maxrel'] = max(acc['maxrel'], rel if a!=0 else 0)
        if rel > 0.005 and d > 1e-9: acc['bad'].append((path,a,b))
    else:
        if a != b and not (a is None and b is None):
            acc['strmis'].append((path, str(a)[:60], str(b)[:60]))
res = {}
# weekly
prior = json.load(open(f"{C}/prior_code/weekly_final_rows.json"))
new = json.load(open(f"{V}/repro/weekly/code/results.json"))["rows"]
key = lambda r: (r["strategy"], r["period"], r.get("variant"))
nd = {key(r): r for r in new}
acc = dict(n=0, bad=[], maxrel=0.0, missing=[], lenmis=[], strmis=[])
nrows = 0
for r in prior:
    if key(r) in nd:
        nrows += 1; walk(r, nd[key(r)], str(key(r)), acc)
    else:
        acc['missing'].append(str(key(r)))
res['weekly'] = dict(rows_matched=nrows, prior_rows=len(prior), **{k:(v if not isinstance(v,list) else v[:8]) for k,v in acc.items()}, nbad=len(acc['bad']), nmiss=len(acc['missing']))
for s in ("C2","C5","C9"):
    p = json.load(open(f"{C}/prior_code/{s}_result.json")); n = json.load(open(f"{V}/repro/{s}/result.json"))
    acc = dict(n=0, bad=[], maxrel=0.0, missing=[], lenmis=[], strmis=[])
    walk(p, n, s, acc)
    res[s] = dict(**{k:(v if not isinstance(v,list) else v[:8]) for k,v in acc.items()}, nbad=len(acc['bad']), nmiss=len(acc['missing']), nstr=len(acc['strmis']))
print(json.dumps(res, indent=1, default=str))
