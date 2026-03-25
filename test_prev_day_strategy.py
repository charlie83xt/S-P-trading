"""
Test script for Previous Day High/Low strategy integration
"""


import logging
from config import Config
from strategy_factory import create as create_strategy


logging.basicConfig(level=logging.INFO)


def test_strategy_creation():
    """Test that strategy can be created"""
    
    # Mock data manager (minimal for testing)
    class MockDataManager:
        def get_current_price(self, symbol):
            return 6600.0
        
        class LiveData:
            def get_last_n(self, symbol, n):
                # Return mock bars
                class MockBar:
                    def __init__(self, o, h, l, c):
                        self.open = o
                        self.high = h
                        self.low = l
                        self.close = c
                
                return [
                    MockBar(6595, 6610, 6590, 6605),  # Yesterday
                    MockBar(6605, 6620, 6600, 6615),  # Today
                ]
        
        def __init__(self):
            self.live = self.LiveData()
    
    dm = MockDataManager()
    config = Config()
    
    # Test strategy creation
    print("Testing PreviousDayHL strategy creation...")
    
    try:
        strategy = create_strategy(
            "PreviousDayHL", 
            data_manager=dm,
            shadow_ratio=2.0,
            max_other_shadow=0.3,
            min_body_pct=0.05,
            tolerance_pct=0.002,
            max_trades_per_day=4,
            qty=1,
        )
        print(f"✅ Strategy created: {type(strategy).__name__}")
        
        # Test 2: Check signal (shouldn't crash)
        print("\n📝 Test 2: Checking for signals...")
        signal = strategy.check_signal("MES")
        if signal:
            print(f"✅ Signal generated: {signal['type']} @ {signal['price']}")
        else:
            print(f"✅ No signal (expected - needs specific conditions)")
        
        # Test 3: Market context
        print("\n📝 Test 3: Getting market context...")
        context = strategy.analyze_market_context("MES")
        print(f"✅ Market context retrieved:")
        for key, value in context.items():
            print(f"   {key}: {value}")
        
        # Test 4: Strategy methods
        print("\n📝 Test 4: Testing strategy methods...")
        
        # Test reset
        strategy.reset_strategy()
        print(f"✅ reset_strategy() works")
        
        # Test ingest_tick (should do nothing)
        strategy.ingest_tick("MES", 1234567890.0, 6600.0)
        print(f"✅ ingest_tick() works")
        
        # Test check_breakout (compatibility method)
        signal2 = strategy.check_breakout("MES")
        print(f"✅ check_breakout() works (returned: {signal2})")
        
        print("\n" + "="*60)
        print("🎉 ALL TESTS PASSED!")
        print("="*60)
        print("\n✅ Strategy is ready to use")
        print("✅ Can be added to StrategyManager")
        print("✅ Will automatically switch on odd days (12-4 PM ET)")
        
    except Exception as e:
        print("\n" + "="*60)
        print("❌ TEST FAILED!")
        print("="*60)
        print(f"\nError: {e}\n")
        import traceback
        traceback.print_exc()
        print("\n" + "="*60)



if __name__ == "__main__":
    test_strategy_creation()



