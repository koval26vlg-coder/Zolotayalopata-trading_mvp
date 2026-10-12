import json, math, sys
def walk(a, b, path, out):
    if isinstance(a, dict):
        assert isinstance(b, dict), path
        for k in a:
            if k not in b: out['missing'].append(path+'/'+k); continue
            walk(a[k], b[k], path+'/'+str(k), out)
    elif isinstance(a, list):
        if len(a)!=len(b): out['lenmismatch'].append(path); return
        for i,(x,y) in enumerate(zip(a,b)): walk(x,y,path+f'[{i}]',out)
    elif isinstance(a,(int,float)) and not isinstance(a,bool):
        out['n']+=1
        if not isinstance(b,(int,float)): out['type'].append(path); return
        if math.isinf(a) or math.isinf(b):
            if a!=b: out['diff'].append((path,a,b)); return
        d = abs(a-b)/max(abs(a),1e-12) if a!=0 else abs(b)
        out['maxrel']=max(out['maxrel'],d)
        if d>0.005: out['diff'].append((path,a,b))
    else:
        out['other']+=1
        if a!=b and 'sha' not in path and 'file' not in path: out['strdiff'].append((path,str(a)[:60],str(b)[:60]))
for s in ['C1','C11','C16']:
    a=json.load(open(f'prior_code/{s}_result.json')); b=json.load(open(f'T3/verify/repro/{s}/result.json'))
    out=dict(n=0,maxrel=0.0,diff=[],missing=[],lenmismatch=[],type=[],other=0,strdiff=[])
    walk(a,b,'',out)
    print(s, 'numeric=',out['n'],'maxrel=',out['maxrel'],'diffs>0.5%=',out['diff'][:5],'missing=',out['missing'][:5],'len=',out['lenmismatch'],'strdiff=',out['strdiff'][:5])
