"""Performance statistics, including the Deflated Sharpe Ratio (Bailey & Lopez de Prado, 2014),
which corrects a Sharpe ratio for the number of strategies tried."""
import math

import numpy as np
import pandas as pd
from statistics import NormalDist

N01 = NormalDist()
EULER_GAMMA = 0.5772156649


def daily_pnl(trades, days):
    """Daily P&L including days with no trades (zeros), aligned to the full calendar of `days`."""
    s = trades.groupby("date").usd.sum() if len(trades) else pd.Series(dtype=float)
    return pd.Series([float(s.get(d.date, 0.0)) for d in days], index=[d.date for d in days])


def sharpe(daily):
    sd = daily.std(ddof=1)
    return 0.0 if not sd or np.isnan(sd) else float(daily.mean() / sd)      # per-day (not annualised)


def bootstrap_ci(x, n=5000, q=(5, 95), seed=0):
    x = np.asarray(x, float)
    if len(x) < 2:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    means = rng.choice(x, (n, len(x))).mean(axis=1)
    lo, hi = np.percentile(means, q)
    return float(lo), float(hi)


def deflated_sharpe(sr, daily, n_trials, sr_variance):
    """Probability that the true Sharpe is > 0 after accounting for `n_trials` attempts.
    sr: per-day Sharpe of this strategy; sr_variance: variance of per-day Sharpe across all trials."""
    t = len(daily)
    if t < 3:
        return float("nan")
    skew = float(pd.Series(daily).skew())
    kurt = float(pd.Series(daily).kurt()) + 3.0          # pandas gives excess kurtosis
    if n_trials > 1 and sr_variance > 0:
        sr0 = math.sqrt(sr_variance) * ((1 - EULER_GAMMA) * N01.inv_cdf(1 - 1 / n_trials)
                                        + EULER_GAMMA * N01.inv_cdf(1 - 1 / (n_trials * math.e)))
    else:
        sr0 = 0.0
    denom = 1 - skew * sr + (kurt - 1) / 4 * sr ** 2
    if denom <= 0:
        return float("nan")
    return float(N01.cdf((sr - sr0) * math.sqrt(t - 1) / math.sqrt(denom)))


def summary(trades, days):
    d = daily_pnl(trades, days)
    eq = d.cumsum()
    lo, hi = bootstrap_ci(trades.usd) if len(trades) else (float("nan"),) * 2
    return dict(
        days=len(days), trades=int(len(trades)),
        total_usd=round(float(trades.usd.sum()), 2) if len(trades) else 0.0,
        avg_usd=round(float(trades.usd.mean()), 2) if len(trades) else 0.0,
        avg_ci90=(round(lo, 2), round(hi, 2)),
        win_rate=round(float((trades.usd > 0).mean()), 3) if len(trades) else 0.0,
        max_drawdown_usd=round(float((eq - eq.cummax()).min()), 2),
        sharpe_daily=round(sharpe(d), 4),
        sharpe_annual=round(sharpe(d) * math.sqrt(252), 2),
        costs_paid_usd=round(len(trades) * 3.74, 2),
    )
