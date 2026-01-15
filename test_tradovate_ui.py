import os
from tradovate_web_ui_api import TradovateWebUIAPI

if __name__ == "__main__":
    api = TradovateWebUIAPI(
        headless=False, # see the browser
        dry_run=True, # don’t click Submit
        fixture_html_path=os.getenv("FIXTURE")  # point this to your saved HTML snapshot for offline tests
    )
    assert api.connect()
        
    print("Probe:", api.probe_selectors())

    bal = api.get_balance()
    print("Balance (from DOM):", bal)
    
    # Try a dry-run buy
    resp = api.place_market_order("MES", "BUY", 1)
    print("Dry-run order:", resp)
    
    input("✅ Dry run complete. Press Enter to close the browser...")
    
    api.disconnect()






