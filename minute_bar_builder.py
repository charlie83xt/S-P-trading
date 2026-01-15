from dataclasses import dataclass
from typing import List, Optional
import math, time

@dataclass
class Bar:
    ts_open: int # unix epoch seconds (start of minute)
    open: float
    high: float
    low: float
    close: float


class MinuteBarBuilder:
    def __init__(self, keep: int = 240):
        self.keep = keep
        self._bars: List[Bar] = []

    @staticmethod
    def _minute_start(ts: float) -> int:
        return int(ts) - (int(ts) % 60)


    def update(self, ts: Optional[float], price: Optional[float]) -> Optional[Bar]:
        if price is None:
            return None
        if ts is None:
            ts = time.time()
        ms = self._minute_start(ts)
        if not self._bars or self._bars[-1].ts_open != ms:
            # start new minute bar
            b = Bar(ts_open=ms, open=price, high=price, low=price, close=price)
            self._bars.append(b)
            if len(self._bars) > self.keep:
                self._bars = self._bars[-self.keep:]
            return b
        else:
            b = self._bars[-1]
            if price > b.high: b.high = price
            if price < b.low: b.low = price
            b.close = price
            return b

    def last_n(self, n: int) -> List[Bar]:
        return self._bars[-n:] if n > 0 else []

    
    def all(self) -> List[Bar]:
        return list(self._bars)