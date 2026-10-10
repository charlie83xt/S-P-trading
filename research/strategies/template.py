"""Copy this file to write a new strategy (you or an agent). Rules the harness relies on:

- on_bar(i, bars) only sees bars[0..i] (bar i has just closed). Never read files or future data.
- Return an Entry to trade at bar i's close, or None. One position at a time.
- Put every tunable number in self.params: the registry records them, and each new combination
  counts as a new trial (which raises the bar every later strategy must clear).
Minute index m: 0 = 09:30 ET, 15 = 09:45, 60 = 10:30, 120 = 11:30, 389 = 15:59.
"""
from research.backtest import Entry


class Strategy:
    name = "template_do_nothing"

    def __init__(self):
        self.params = {}

    def reset(self, day):
        # day.date, day.pdh, day.pdl, day.pclose (previous regular-hours high/low/close)
        self.day = day

    def on_bar(self, i, bars):
        # bars.m, bars.open, bars.high, bars.low, bars.close, bars.volume -> numpy arrays up to bar i
        return None
