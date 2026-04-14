"""
Local Session Keepalive - For Daily Trading Sessions

Lightweight heartbeat for local laptop trading.
Prevents Tradovate session timeout during your 6-8 hour trading day.
"""

import time
import threading
from datetime import datetime, timedelta
import logging
from debug_config import debug_print, production_print

logger = logging.getLogger(__name__)


class LocalSessionKeepAlive:
    """
    Simplified keepalive for local trading sessions.
    
    Designed for traders who:
    - Run bot during market hours (6-8 hours/day)
    - Shut down overnight
    - Use their laptop for trading
    """
    
    def __init__(self, api, interval_minutes=15):
        """
        Initialize local keepalive.
        
        Args:
            api: Your TradovateUI or API instance
            interval_minutes: How often to ping (default 15 minutes)
                             15 min is good balance - not too frequent, prevents timeout
        """
        self.api = api
        self.interval = timedelta(minutes=interval_minutes)
        self.last_heartbeat = datetime.now()
        self.running = False
        self.thread = None
        self.ping_count = 0
    
    def start(self):
        """Start keepalive when you begin trading session"""
        if self.running:
            logger.warning("Keepalive already running")
            return
        
        self.running = True
        self.ping_count = 0
        self.thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self.thread.start()
        
        timestamp = datetime.now().strftime('%H:%M:%S')
        logger.info(f"🔄 [{timestamp}] Session keepalive started (ping every {self.interval.total_seconds()/60:.0f} minutes)")
    
    def stop(self):
        """Stop keepalive when you end trading session"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        
        timestamp = datetime.now().strftime('%H:%M:%S')
        logger.info(f"⏸️  [{timestamp}] Session keepalive stopped ({self.ping_count} pings sent today)")
    
    def _heartbeat_loop(self):
        """Background loop that sends periodic pings"""
        while self.running:
            try:
                # Check if it's time for a heartbeat
                time_since_last = datetime.now() - self.last_heartbeat
                
                if time_since_last > self.interval:
                    self._ping()
                    self.last_heartbeat = datetime.now()
                    self.ping_count += 1
                    
            except Exception as e:
                logger.error(f"Heartbeat loop error: {e}")
            
            # Sleep for 1 minute, then check again
            time.sleep(60)
    
    def _ping(self):
        """Send a lightweight ping to keep session alive"""
        try:
            timestamp = datetime.now().strftime('%H:%M:%S')
            
            # ✅ FIX: Check for Playwright FIRST (your actual API)
            if hasattr(self.api, '_page') and self.api._page:
                try:
                    import asyncio
                    
                    # Get or create event loop
                    try:
                        loop = asyncio.get_event_loop()
                    except RuntimeError:
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                    
                    # Execute JavaScript via Playwright
                    loop.run_until_complete(
                        self.api._page.evaluate("() => console.log('keepalive ping')")
                    )
                    logger.info(f"✓ [{timestamp}] Session ping #{self.ping_count + 1} sent (Playwright)")
                    return
                except Exception as e:
                    logger.warning(f"⚠️  [{timestamp}] Playwright ping failed: {e}")
            
            # Fallback: Try REST API if available
            elif hasattr(self.api, 'get_account_info'):
                try:
                    account_info = self.api.get_account_info()
                    if account_info and 'error' not in account_info:
                        logger.info(f"✓ [{timestamp}] Session ping #{self.ping_count + 1} sent (REST API)")
                        return
                except Exception as e:
                    logger.warning(f"⚠️  [{timestamp}] REST API ping failed: {e}")
            
            # If nothing worked
            logger.warning(f"⚠️  [{timestamp}] No valid ping method found")
                
        except Exception as e:
            timestamp = datetime.now().strftime('%H:%M:%S')
            logger.warning(f"⚠️  [{timestamp}] Ping failed: {e} (will retry next interval)")

    
    def force_ping(self):
        """
        Manually trigger a ping (useful for testing or after suspicious inactivity)
        
        Usage:
            keepalive.force_ping()
        """
        logger.info("🔧 Manual ping requested")
        self._ping()
        self.last_heartbeat = datetime.now()
    
    def get_status(self):
        """
        Get current keepalive status
        
        Returns:
            dict: Status information
        """
        time_since_last = datetime.now() - self.last_heartbeat
        next_ping_in = self.interval - time_since_last
        
        return {
            'running': self.running,
            'pings_sent': self.ping_count,
            'last_ping': self.last_heartbeat.strftime('%H:%M:%S'),
            'next_ping_in_seconds': max(0, int(next_ping_in.total_seconds())),
            'interval_minutes': int(self.interval.total_seconds() / 60)
        }


# ============================================================================
# EXAMPLE USAGE
# ============================================================================

if __name__ == "__main__":
    # Configure logging for testing
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    )
    
    # Mock API for testing
    class MockTradovateUI:
        def __init__(self):
            self.driver = True  # Simulate browser driver
    
    debug_print("=== Local Session Keepalive Test ===\n")
    
    # Create mock API
    api = MockTradovateUI()
    
    # Create keepalive with 1-minute interval (for testing - normally use 15)
    keepalive = LocalSessionKeepAlive(api, interval_minutes=1)
    
    debug_print("Starting keepalive...")
    keepalive.start()
    
    # Simulate trading session for 5 minutes
    debug_print("\nSimulating 5-minute trading session...")
    debug_print("(In real use, this runs in background while your bot trades)")
    
    for i in range(5):
        time.sleep(60)
        status = keepalive.get_status()
        debug_print(f"\nAfter {i+1} minutes:")
        debug_print(f"  Pings sent: {status['pings_sent']}")
        debug_print(f"  Last ping: {status['last_ping']}")
        debug_print(f"  Next ping in: {status['next_ping_in_seconds']}s")
    
    debug_print("\n\nStopping keepalive...")
    keepalive.stop()
    
    debug_print("\nTest complete!")
    debug_print("\nTo use in your bot:")
    debug_print("  from heartbeat_local import LocalSessionKeepAlive")
    debug_print("  keepalive = LocalSessionKeepAlive(api, interval_minutes=15)")
    debug_print("  keepalive.start()  # When you start trading")
    debug_print("  # ... your bot runs ...")
    debug_print("  keepalive.stop()   # When you stop trading")
