"""
Volume-profile helpers.

In the real bot the FRVP levels (VAH/POC/VAL) are drawn pre-session from the
prior ETH session and passed in as SessionLevels. This module provides a simple
fallback profile computation and a few membership/distance helpers used by the
detectors. Nothing here is an entry decision -- just geometry.
"""

from __future__ import annotations

from typing import Iterable

from .types import Bar, SessionLevels


def inside_va(price: float, levels: SessionLevels) -> bool:
    return levels.val <= price <= levels.vah


def at_edge(price: float, levels: SessionLevels, tol: float) -> str | None:
    """Return 'vah' / 'val' if price is within tol of that edge, else None."""
    if abs(price - levels.vah) <= tol:
        return "vah"
    if abs(price - levels.val) <= tol:
        return "val"
    return None


def poc_distance(price: float, levels: SessionLevels) -> float:
    return price - levels.poc


def compute_profile(bars: Iterable[Bar], session_date, pdh: float, pdl: float,
                    bin_size: float = 1.0, value_area_pct: float = 0.70
                    ) -> SessionLevels:
    """Crude fixed-bin volume profile -> POC/VAH/VAL.

    Distributes each bar's volume evenly across the price bins its range spans.
    This is a fallback for testing only; the live bot should pass real FRVP
    levels. value_area_pct defaults to the standard 70%.
    """
    bins: dict[float, float] = {}
    for b in bars:
        lo = round(b.low / bin_size) * bin_size
        hi = round(b.high / bin_size) * bin_size
        steps = int(round((hi - lo) / bin_size)) + 1
        if steps <= 0:
            steps = 1
        share = b.volume / steps
        p = lo
        for _ in range(steps):
            bins[p] = bins.get(p, 0.0) + share
            p += bin_size

    if not bins:
        raise ValueError("no volume to build a profile")

    poc = max(bins, key=lambda k: bins[k])
    total = sum(bins.values())
    target = total * value_area_pct

    # Expand outward from POC until we cover the value-area volume.
    prices_sorted = sorted(bins)
    poc_idx = prices_sorted.index(poc)
    lo_idx = hi_idx = poc_idx
    covered = bins[poc]
    while covered < target and (lo_idx > 0 or hi_idx < len(prices_sorted) - 1):
        low_vol = bins[prices_sorted[lo_idx - 1]] if lo_idx > 0 else -1
        high_vol = bins[prices_sorted[hi_idx + 1]] if hi_idx < len(prices_sorted) - 1 else -1
        if high_vol >= low_vol:
            hi_idx += 1
            covered += bins[prices_sorted[hi_idx]]
        else:
            lo_idx -= 1
            covered += bins[prices_sorted[lo_idx]]

    val = prices_sorted[lo_idx]
    vah = prices_sorted[hi_idx]
    return SessionLevels(session_date=session_date, vah=vah, poc=poc, val=val,
                         pdh=pdh, pdl=pdl) 
