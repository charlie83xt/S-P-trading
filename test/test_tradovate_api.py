from tradovate_api import TradovateAPI
from config import Config


cfg = Config()


# Initialize API
api = TradovateAPI(
    username=cfg.TRADOVATE_USERNAME,
    password=cfg.TRADOVATE_PASSWORD,
    demo=True  # Use paper trading
)


# Test connection
print("Testing Tradovate API connection...")
if api.connect():
    print("✓ Connected successfully!")
   
    # Test account info
    account = api.get_account_info()
    print(f"Account info: {account}")
   
    # Test price retrieval
    price = api.get_current_price("ES")
    print(f"ES Current Price: {price}")
   
    # Test positions
    positions = api.get_positions()
    print(f"Current positions: {positions}")
   
    # Disconnect
    api.disconnect()
    print("✓ Test complete!")
else:
    print("✗ Connection failed!")




