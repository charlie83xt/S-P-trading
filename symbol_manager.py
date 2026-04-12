import logging

class SymbolManager:
    """
    Centralized symbol management for the trading bot.
    Change symbol in ONE place, everything updates.
    """
   
    def __init__(self, config):
        self.config = config
        self._active_symbol = config.DEFAULT_SYMBOL
        self.logger = logging.getLogger(__name__)
   
    @property
    def symbol(self) -> str:
        """Get current active symbol"""
        return self._active_symbol
   
    @symbol.setter
    def symbol(self, new_symbol: str):
        """Change symbol - validates and updates everywhere"""
        new_symbol = new_symbol.upper()
       
        # Validate symbol has a multiplier
        if new_symbol not in self.config.CONTRACT_MULTIPLIERS:
            raise ValueError(
                f"Unknown symbol: {new_symbol}. "
                f"Valid symbols: {list(self.config.CONTRACT_MULTIPLIERS.keys())}"
            )
       
        old_symbol = self._active_symbol
        self._active_symbol = new_symbol
       
        self.logger.info(f"📊 Symbol changed: {old_symbol} → {new_symbol}")
        self.logger.info(f"   Multiplier: ${self.get_multiplier()}/point")
   
    def get_multiplier(self) -> float:
        """Get contract multiplier for active symbol"""
        return self.config.CONTRACT_MULTIPLIERS.get(self._active_symbol, 1.0)
   
    def get_tick_size(self) -> float:
        """Get minimum tick size for active symbol"""
        # ES/MES = 0.25, NQ/MNQ = 0.25, etc.
        return 0.25
   
    def get_tick_value(self) -> float:
        """Get dollar value per tick"""
        return self.get_multiplier() / 4  # 4 ticks per point



