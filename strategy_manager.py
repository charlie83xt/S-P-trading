"""
Multi-Strategy Portfolio Manager
Handles strategy selection, switching, and performance monitoring
"""

import time
import logging
from datetime import datetime
from typing import Dict, Optional, Any
from zoneinfo import ZoneInfo

from trade_analytics import TradeAnalytics
from strategy_factory import create as create_strategy
from debug_config import LOADING, WARNING, CHECK, WRENCH, CHART

ET_TZ = ZoneInfo("America/New_York")


class StrategyManager:
    """
    Manages multiple strategies and switches between them based on:
    1. Time of day (different strategies for different sessions)
    2. Performance (pause underperformers)
    3. Market conditions (volatility, volume)
    """
   
    def __init__(self, data_manager, config, analytics: TradeAnalytics):
        self.dm = data_manager
        self.config = config
        self.analytics = analytics
        self.logger = logging.getLogger(__name__)
       
        # Initialize all strategies
        self.strategies = self._initialize_strategies()
       
        # Current active strategy
        self.current_strategy_name = None
        self.current_strategy = None
       
        # Performance tracking
        self.strategy_stats = {}
        self.last_performance_check = 0
        self.performance_check_interval = 3600  # Check every hour
       
        # Paused strategies (underperformers)
        self.paused_strategies = set()
        self.manual_override = False
        self.manual_strategy_name = None
   
    def _initialize_strategies(self) -> Dict[str, Any]:
        """Create all strategy instances"""
        strategies = {}
       
        # ORBRetest for US market open (9:45 AM - 12:00 PM ET)
        strategies["ORBRetest"] = create_strategy(
            "ORBRetest",
            data_manager=self.dm,
            opening_range_minutes=self.config.ORB_RETEST_OR_MINUTES,
            breakout_points=self.config.ORB_RETEST_BREAKOUT_POINTS,
            trade_start_time_et=(9, 45),
            trade_end_time_et=(12, 0)
        )

        # MeanReversion for afternoon session (12:00 PM - 4:00 PM ET) in odd days
        strategies["MeanReversion"] = create_strategy(
            "MeanReversion",
            data_manager=self.dm,
            lookback=getattr(self.config, 'MEAN_REVERSION_LOOKBACK', 20),
            std_dev=getattr(self.config, 'MEAN_REVERSION_STD_DEV', 2.0),
            max_trades_per_day=getattr(self.config, 'MEAN_REVERSION_MAX_TRADES', 4),
            min_bandwith_pct=getattr(self.config, 'MEAN_REVERSION_MIN_BANDWIDTH', 0.0010),
            cooldown_bars=getattr(self.config, 'MEAN_REVERSION_COOLDOWN_BARS', 3),
            require_reentry_confirmation=getattr(self.config, 'MEAN_REVERSION_REQUIRE_CONFIRMATION', True)
        )

        # MeanReversion (Old) for afternoon session (12:00 PM - 4:00 PM ET) in even days
        strategies["MeanReversionOld"] = create_strategy(
            "MeanReversionOld",
            data_manager=self.dm,
            lookback=getattr(self.config, 'MEAN_REVERSION_LOOKBACK', 20),
            std_dev=getattr(self.config, 'MEAN_REVERSION_STD_DEV', 2.0),
            max_trades_per_day=getattr(self.config, 'MEAN_REVERSION_MAX_TRADES', 4),
        )

        # PreviousDayHL for afternoon session (12:00 PM - 4:00 PM ET) on odd days
        strategies["PreviousDayHL"] = create_strategy(
            "PreviousDayHL",
            data_manager=self.dm,
            shadow_ratio=2.0,
            max_other_shadow=0.3,
            min_body_pct=0.05,
            tolerance_pct=0.002,
            max_trades_per_day=4,
            qty=1,
        )
        
        # OpeningRange for early morning (8:00 AM - 9:45 AM ET)
        strategies["OpeningRange"] = create_strategy(
            "OpeningRange",
            data_manager=self.dm,
            opening_range_minutes=30,
        )
        
        # Add more strategies as you build them
        # strategies["MeanReversion"] = create_strategy("MeanReversion", ...)
        # strategies["RangeTrader"] = create_strategy("RangeTrader", ...)
       
        self.logger.info(f"Initialized {len(strategies)} strategies: {list(strategies.keys())}")
        return strategies
   
    def get_active_strategy(self, ts: Optional[float] = None) -> Any:
        """
        Select which strategy should be active right now based on:
        1. Time of day (primary selector)
        2. Performance (pause underperformers)
        3. Market conditions (future enhancement)
        """
        if ts is None:
            ts = time.time()

        # Check manual override FIRST
        if getattr(self, 'manual_override', False):
            manual_name = getattr(self, 'manual_strategy_name', None)
            if manual_name and manual_name in self.strategies:
                if self.current_strategy_name != manual_name:
                    self.logger.info(f"{WRENCH} MANUAL MODE: {manual_name}")
                    self.current_strategy_name = manual_name
                    self.current_strategy = self.strategies[manual_name]
                return self.current_strategy
       
        # Convert to Eastern Time
        current_et = datetime.fromtimestamp(ts, tz=ET_TZ)
        hour = current_et.hour
        minute = current_et.minute
       
        # Time-based strategy selection
        strategy_name = self._select_by_time(hour, minute)
       
        # Check if strategy is paused due to poor performance
        if strategy_name in self.paused_strategies:
            strategy_name = self._get_fallback_strategy(hour)
            self.logger.warning(
                f"Primary strategy {strategy_name} is paused, "
                f"using fallback"
            )
       
        # Switch strategies if needed
        if strategy_name != self.current_strategy_name:
            self.logger.info(
                f"{LOADING} STRATEGY SWITCH: {self.current_strategy_name} -> {strategy_name} "
                f"(ET time: {current_et.strftime('%H:%M')})"
            )
            self.current_strategy_name = strategy_name
            self.current_strategy = self.strategies[strategy_name]
       
        # Periodic performance check
        self._check_strategy_performance(ts)
       
        return self.current_strategy
   
    def _select_by_time(self, hour_et: int, minute_et: int) -> str:
        """
        Select strategy based on Eastern Time hour.
       
        Time windows:
        - 9:45 AM - 12:00 PM: ORBRetest (US market open - high volatility)
        - 12:00 PM - 4:00 PM: MeanReversion (afternoon chop)
        - 4:00 PM - 8:00 AM: OFF (overnight - you're sleeping)
        - 8:00 AM - 9:45 AM: OpeningRange (pre-market - simpler strategy)
        """
        if (hour_et == 9 and minute_et >= 45) or (10 <= hour_et < 12): # 9:45 - 12:00 PM
            return "ORBRetest"
        elif 12 <= hour_et < 16: 
            # A/B Test: Temporary alternating between new and old strategy 12:00 PM - 4:00 PM
            current_day = datetime.now(ET_TZ).day

            # if current_day % 2 == 0:
            #     # Even days: use old strategy
            #     self.logger.debug(f"{CHART} A/B: Even day {current_day} -> MeanReversion")
            #     return "MeanReversion"
            # else:
            #     # Odd days: Use new strategy
            #     self.logger.debug(f"{CHART} A/B: Odd day {current_day} -> PreviousDayHL")
            #     return "PreviousDayHL"
            self.logger.debug(f"{CHART} A/B: Even day {current_day} -> MeanReversion")
            return "MeanReversion"

        elif 8 <= hour_et < 9:
            return "OpeningRange"  # Add when built
        else:
            # Outside trading hours - use safest/simplest strategy
            return "OpeningRange"
   
    def _get_fallback_strategy(self, hour_et: int) -> str:
        """Get alternative strategy if primary is paused"""
        # Always fall back to OpeningRange (simplest, most reliable)
        return "OpeningRange"
   
    def _check_strategy_performance(self, ts: float):
        """
        Periodically check strategy performance and pause underperformers.
       
        Pause criteria:
        - Win rate < 40% (over last 20 trades)
        - Consecutive losses > 5
        - Drawdown > 1.5x average win
        """
        # Only check once per hour
        if ts - self.last_performance_check < self.performance_check_interval:
            return
       
        self.last_performance_check = ts
       
        # Get recent performance for all strategies
        stats = self.analytics.get_strategy_performance(days=7)
       
        for strategy_name, perf in stats.items():
            # Skip if not enough trades
            if perf['trades'] < 10:
                continue
           
            # Pause if win rate too low
            if perf['win_rate'] < 40:
                self.paused_strategies.add(strategy_name)
                self.logger.warning(
                    f"{WARNING}  PAUSING {strategy_name}: "
                    f"Win rate {perf['win_rate']}% < 40%"
                )
           
            # Pause if losing money
            elif perf['total_pnl'] < -500:  # Adjust threshold
                self.paused_strategies.add(strategy_name)
                self.logger.warning(
                    f"{WARNING}  PAUSING {strategy_name}: "
                    f"Total PnL ${perf['total_pnl']:.2f} < -$500"
                )
           
            # Resume if performance improved
            elif (strategy_name in self.paused_strategies and
                  perf['win_rate'] > 50 and perf['total_pnl'] > 0):
                self.paused_strategies.discard(strategy_name)
                self.logger.info(
                    f"{CHECK} RESUMING {strategy_name}: "
                    f"Win rate {perf['win_rate']}%, PnL ${perf['total_pnl']:.2f}"
                )
       
        self.strategy_stats = stats
   
    def get_portfolio_summary(self) -> Dict[str, Any]:
        """Get overview of all strategies for dashboard"""
        return {
            'current_strategy': self.current_strategy_name,
            'available_strategies': list(self.strategies.keys()),
            'paused_strategies': list(self.paused_strategies),
            'strategy_stats': self.strategy_stats
        }


