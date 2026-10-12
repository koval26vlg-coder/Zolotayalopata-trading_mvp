# Exact enumeration of the permutation null for small-spell cases (C2 OOS, C5 OOS, S2 OOS)
import itertools, math, numpy as np, sys
sys.argv = [sys.argv[0]]
import verify_t1 as V
S = V.build()
for key in [("C2", "OOS"), ("C5", "OOS"), ("S2", "OOS"), ("C5", "IS")]:
    s = S[key][0]
    lens, st = s.runs()
    sp, gp, s0 = lens[st == 1], lens[st == 0], int(st[0])
    act = s.net()
    vals = []
    for a in set(itertools.permutations(sp.tolist())):
        for b in set(itertools.permutations(gp.tolist())):
            L = [None] * (len(a) + len(b))
            if s0 == 1: L[0::2], L[1::2] = a, b
            else: L[0::2], L[1::2] = b, a
            vals.append(s.net(s.schedule_from_L(L, s0)))
    vals = np.array(vals)
    print(key, "spells", sp.tolist(), "gaps", gp.tolist(), "start", s0, "n_orderings", len(vals),
          "actual", round(act, 4), "exact_p(>=)", round(float((vals >= act - 1e-9).mean()), 4),
          "exact_median", round(float(np.median(vals)), 4),
          "values", sorted(np.round(vals, 3).tolist())[:12] if len(vals) <= 12 else "")
