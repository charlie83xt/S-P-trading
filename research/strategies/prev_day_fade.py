"""Hypothesis tested in chat (failed on MES 2024-25): fade a break of the previous day's high/low
that is still holding 5 minutes after the first cross, 09:30-11:30 ET."""
from research.backtest import Entry


class Strategy:
    name = "prev_day_fade"

    def __init__(self):
        self.params = {"hold_min": 5, "stop_pts": 8.0, "target_pts": 8.0, "last_entry_m": 120,
                       "exit_at_m": 150}

    def reset(self, day):
        self.day, self.cross = day, {}          # level -> minute of first cross

    def on_bar(self, i, bars):
        p, m = self.params, int(bars.m[i])
        if m >= p["last_entry_m"]:
            return None
        for lvl, side in ((self.day.pdh, 1), (self.day.pdl, -1)):
            hit = bars.high[i] > lvl if side > 0 else bars.low[i] < lvl
            if lvl not in self.cross and hit:
                self.cross[lvl] = m
            if self.cross.get(lvl) is not None and m == self.cross[lvl] + p["hold_min"]:
                self.cross[lvl] = None            # evaluate once per level per day
                still = bars.close[i] >= lvl if side > 0 else bars.close[i] <= lvl
                if still:
                    return Entry(side=-side, stop_pts=p["stop_pts"], target_pts=p["target_pts"],
                                 exit_at_m=p["exit_at_m"])
        return None
