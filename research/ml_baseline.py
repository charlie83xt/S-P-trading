"""ML baseline: gradient boosting predicts whether MES is higher 30 minutes later, every 5 minutes
09:45-11:00 ET. Trains on the design year, tests once on the validation year. Shows how large the
gap between in-sample and out-of-sample results is (in chat: AUC 0.87 -> 0.50).

    python -m research.ml_baseline --design <2024-25 file> --validate <2025-26 file>
"""
import argparse

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score

from .backtest import COST_PER_TRADE, POINT_VALUE
from .data import load_days

HORIZON = 30


def features(days):
    rows = []
    for d in days:
        c, idx = d.close, {int(m): k for k, m in enumerate(d.m)}
        o15 = [k for k, m in enumerate(d.m) if m < 15]
        if not o15:
            continue
        orh, orl = d.high[o15].max(), d.low[o15].min()
        vwap = np.cumsum(d.close * d.volume) / np.maximum(np.cumsum(d.volume), 1)
        vol0 = np.median(d.volume[o15]) or 1
        for m in range(15, 91, 5):
            if m not in idx or m + HORIZON not in idx:
                continue
            k = idx[m]; p = c[k]
            back = lambda n: c[idx.get(m - n, 0)]
            lo, hi = d.low[:k + 1].min(), d.high[:k + 1].max()
            rows.append(dict(
                tod=m, r5=p - back(5), r15=p - back(15), r30=p - back(min(30, m)),
                from_open=p - d.open[0], gap=d.open[0] - d.pclose,
                d_pdh=p - d.pdh, d_pdl=p - d.pdl, d_orh=p - orh, d_orl=p - orl, d_vwap=p - vwap[k],
                or_w=orh - orl, day_rng=hi - lo, pos_in_rng=(p - lo) / ((hi - lo) or 1),
                vol_ratio=d.volume[max(k - 4, 0):k + 1].mean() / vol0,
                y_pts=c[idx[m + HORIZON]] - p))
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--design", required=True)
    ap.add_argument("--validate", required=True)
    a = ap.parse_args()
    tr, te = features(load_days(a.design)), features(load_days(a.validate))
    X = [k for k in tr.columns if k != "y_pts"]
    clf = HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=300, random_state=0)
    clf.fit(tr[X], tr.y_pts > 0)
    for name, df in (("DESIGN (in-sample)", tr), ("VALIDATION (unseen)", te)):
        p = clf.predict_proba(df[X])[:, 1]
        y = df.y_pts > 0
        print(f"{name}: n={len(df)} accuracy {np.mean((p > .5) == y):.1%} AUC {roc_auc_score(y, p):.3f}")
        for thr in (0.55, 0.60):
            sel = (p > thr) | (p < 1 - thr)
            usd = np.where(p[sel] > .5, 1, -1) * df.y_pts.values[sel] * POINT_VALUE - COST_PER_TRADE
            print(f"   confidence > {thr:.0%}: {sel.sum()} trades, avg ${usd.mean():+.2f}, total ${usd.sum():+.0f}")


if __name__ == "__main__":
    main()
