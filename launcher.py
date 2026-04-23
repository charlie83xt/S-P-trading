"""
Main launcher for S-P Trading App.
Cross-platform startup that handles Chrome, dashboard, and authorization.

Usage:
    python launcher.py              # Run with default settings
    python launcher.py --setup      # First-time setup wizard
    python launcher.py --debug      # Debug mode (verbose logging)
"""

import sys
import os
import time
import logging
import argparse
import subprocess
from pathlib import Path
from threading import Thread
from debug_config import CHECK, CROSS, ROCKET, CHART, WRENCH, WARNING, INFO, NOTE, TERRA, RED, BOT
import webbrowser

# Add current directory to path so imports work
sys.path.insert(0, str(Path(__file__).parent))

from chrome_helper import launch_chrome, wait_for_chrome, kill_chrome_on_port
from app_config import (
    load_config, save_config, get_config_value, set_config_value,
    load_env_file, save_env_file, get_log_dir, get_app_config_dir
)
from version import APP_VERSION, load_version_info
from authorization import (
    check_authorization_before_launch, register_machine,
    AuthorizationManager
)

# Setup logging
def setup_logging(debug: bool = False):
    """Configure application logging."""
    log_dir = get_log_dir()
    log_file = log_dir / f"launcher_{time.strftime('%Y%m%d_%H%M%S')}.log"
    
    level = logging.DEBUG if debug else logging.INFO
    
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()
        ]
    )
    
    return logging.getLogger(__name__)

def print_header():
    """Print app header."""
    print("\n" + "="*60)
    print(f"{BOT} S-P TRADING APP")
    print(f"Version: {APP_VERSION}")
    print("="*60 + "\n")

def validate_installation() -> bool:
    """
    Validate that the app installation is complete.
    
    In packaged app, modules are bundled, so check differently.
    """
    logger = logging.getLogger(__name__)
    
    # Check if we're running from PyInstaller bundle
    if getattr(sys, 'frozen', False):
        # Running from PyInstaller bundle
        logger.info("Running from packaged executable")
        
        # Check critical imports can be loaded
        try:
            import trading_bot
            import web_app
            import config
            logger.info("[OK] Core modules loaded successfully")
            return True
        except ImportError as e:
            logger.error(f"[X] Failed to import module: {e}")
            return False
    
    else:
        # Running from source (development)
        required_files = [
            "trading_bot.py",
            "config.py",
            "launch_web_dashboard.py",
        ]
        
        for file in required_files:
            if not Path(file).exists():
                logger.error(f"[X] Missing required file: {file}")
                return False
        
        logger.info("[OK] Installation validation passed")
        return True

def setup_wizard(logger):
    """
    First-time setup wizard.
    Asks user for trading credentials and basic configuration.
    ALSO registers machine for authorization.
    """
    print("\n" + "="*60)
    print(f"{WRENCH} INITIAL SETUP")
    print("="*60 + "\n")
    
    config = load_config()
    
    # AUTHORIZATION: Register this machine
    print(f"{NOTE} Step 1: Machine Registration")
    print("-" * 40)
    config_dir = get_app_config_dir()
    user_email = input("Enter your email address (for license tracking): ").strip()
    
    if not register_machine(config_dir, user_email):
        logger.error(f"{CROSS} Registration failed. Application cannot start.")
        print(f"{CROSS} Registration failed. Please try again.")
        sys.exit(1)
    
    # Ask for trading platform
    print(f"\n{NOTE} Step 2: Trading Configuration")
    print("-" * 40)
    print("Which trading platform do you want to use?")
    print("  1) Tradovate (Recommended for S&P 500 futures)")
    print("  2) Binance (Cryptocurrency futures)")
    print("  3) NinjaTrader (Desktop platform)")
    
    choice = input("Enter choice (1-3): ").strip()
    platforms = {"1": "tradovate_ui", "2": "binance", "3": "ninjatrader"}
    config["trading_platform"] = platforms.get(choice, "tradovate_ui")
    
    # Ask for default symbol
    print("\nDefault trading symbol:")
    print("  - ES (S&P 500 E-mini)")
    print("  - MES (Micro S&P 500)")
    print("  - NQ (Nasdaq E-mini)")
    
    symbol = input("Enter symbol (default: MES): ").strip() or "MES"
    config["default_symbol"] = symbol
    
    # Ask for dry-run mode
    print("\nStart in DRY-RUN mode? (safe for testing)")
    dry_run = input("Dry-run? (yes/no, default: yes): ").strip().lower() != "no"
    config["dry_run"] = dry_run
    
    save_config(config)
    
    # Save environment variables if needed
    if config["trading_platform"] in ("tradovate_ui", "tradovate"):
        print(f"\n{NOTE} Enter your Tradovate credentials:")
        username = input("Tradovate username: ").strip()
        password = input("Tradovate password: ").strip()
        
        env_vars = load_env_file()
        env_vars["TRADOVATE_USERNAME"] = username
        env_vars["TRADOVATE_PASSWORD"] = password
        save_env_file(env_vars)
    
    logger.info(f"{CHECK} Setup wizard completed")
    print(f"\n{CHECK} Setup complete! You can now start the app.\n")

def start_chrome(logger, config: dict) -> bool:
    """
    Start Chrome with remote debugging.
    
    Returns:
        True if Chrome started successfully
    """
    chrome_port = config.get("chrome_port", 9222)
    
    logger.info(f"{TERRA} Launching Chrome on port {chrome_port}...")
    
    # Kill any existing Chrome on this port
    try:
        kill_chrome_on_port(chrome_port)
        time.sleep(1)
    except Exception:
        pass
    
    # Launch new Chrome
    chrome_process = launch_chrome(port=chrome_port)
    if not chrome_process:
        logger.error(f"{CROSS} Failed to launch Chrome")
        return False
    
    # Wait for Chrome to be ready
    if not wait_for_chrome(port=chrome_port, timeout=10):
        logger.error(f"{CROSS} Chrome failed to respond")
        chrome_process.terminate()
        return False
    
    logger.info(f"{CHECK} Chrome ready")
    return True

def start_dashboard(logger, config: dict) -> bool:
    """
    Start the trading dashboard web server.
    
    Returns:
        True if dashboard started successfully
    """
    dashboard_port = config.get("dashboard_port", 5000)
    
    logger.info(f"{CHART} Starting dashboard on port {dashboard_port}...")
    
    try:
        # FIX: Check if running from PyInstaller bundle
        if getattr(sys, 'frozen', False):
            # Running from packaged .exe
            # Import and run directly (don't subprocess)
            logger.info("Starting dashboard from packaged app...")

            # Import and start Flask in a thread
            def run_flask():
                try:
                     # Set environment variables
                    os.environ['PW_MODE'] = 'cdp'
                    os.environ['BROWSER_MODE'] = 'cdp'
                    os.environ['CDP_PORT'] = '9222'
                    os.environ['CDP_URL'] = 'http://localhost:9222'
                    os.environ['PORT'] = str(dashboard_port)

                    logger.info("Environment set: PW_MODE=cdp, CDP_PORT=9222")
                    logger.info(f"  PW_MODE={os.environ.get('PW_MODE')}")
                    logger.info(f"   CDP_PORT={os.environ.get('CDP_PORT')}")
                    
                    # Import web_app (it's bundled in _internal)
                    import web_app
                    # Run Flask
                    web_app.app.run(
                        host='0.0.0.0',
                        port=dashboard_port,
                        debug=False,
                        use_reloader=False  # CRITICAL: No reloader in packaged app
                    )
                except Exception as e:
                    logger.error(f"Flask error: {e}")
                    import traceback
                    traceback.print_exc()
            
            # Start Flask in background thread
            flask_thread = Thread(target=run_flask, daemon=True)
            flask_thread.start()
            
            # Wait for Flask to start
            time.sleep(3)
            
            logger.info(f"{CHECK} Dashboard started in background thread")
            return True
        
        else:
            # Running from source (development mode)
            # Use subprocess as before
            process = subprocess.Popen(
                [sys.executable, "launch_web_dashboard.py"],
                # stdout=subprocess.PIPE,
                # stderr=subprocess.PIPE
            )
            
            # Wait a moment for startup
            time.sleep(3)
            
            if process.poll() is not None:
                logger.error(f"{CROSS} Dashboard process exited unexpectedly")
                return False
            
            logger.info(f"{CHECK} Dashboard started (PID: {process.pid})")
            return True
        
    except Exception as e:
        logger.error(f"{CROSS} Failed to start dashboard: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

def run_app(logger, config: dict):
    """Main application run loop."""
    
    print("\n" + "="*60)
    print(f"{ROCKET} STARTING APPLICATION")
    print("="*60 + "\n")
    
    # ... existing validation code ...
    
    # Start Chrome
    if not start_chrome(logger, config):
        print(f"{CROSS} Failed to start Chrome.")
        return False
    
    # Start dashboard
    if not start_dashboard(logger, config):
        print(f"{CROSS} Failed to start dashboard.")
        return False
    
    # FIX: Auto-open browser to dashboard
    dashboard_port = config.get('dashboard_port', 5000)
    dashboard_url = f"http://localhost:{dashboard_port}"
    
    logger.info(f"Opening browser to {dashboard_url}...")
    
    try:
        # Wait a moment for Flask to fully start
        time.sleep(2)
        # Open browser
        # webbrowser = webbrowser.get('chrome')
        webbrowser.open(dashboard_url)
        logger.info(f"{CHECK} Browser opened")
    except Exception as e:
        logger.warning(f"Could not auto-open browser: {e}")
        logger.info(f"Please open manually: {dashboard_url}")
    
    # Load environment variables
    env_vars = load_env_file()
    os.environ.update(env_vars)
    
    print("\n" + "="*60)
    print(f"{CHECK} APPLICATION RUNNING")
    print("="*60)
    print(f"Dashboard: {dashboard_url}")
    print(f"Chrome debugging: localhost:{config.get('chrome_port', 9222)}")
    print("\nPress Ctrl+C to stop the application.\n")
    
    # Keep the app running
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print(f"\n\n{CROSS} Shutting down...")
        logger.info("Application stopped by user")
    
    return True


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='S-P Trading Application Launcher',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python launcher.py              Run the app
  python launcher.py --setup      Run setup wizard
  python launcher.py --debug      Enable debug logging
        """
    )
    
    parser.add_argument('--setup', action='store_true', help='Run setup wizard')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    parser.add_argument('--version', action='store_true', help='Show version')
    parser.add_argument('--auth-info', action='store_true', help='Show authorization info')
    
    args = parser.parse_args()
    
    # Setup logging
    logger = setup_logging(debug=args.debug)
    
    # Print header
    print_header()
    
    # Handle version flag
    if args.version:
        print(f"Version: {APP_VERSION}")
        return 0
    
    # Handle auth-info flag
    if args.auth_info:
        config_dir = get_app_config_dir()
        auth = AuthorizationManager(config_dir)
        import json
        print(json.dumps(auth.get_authorization_info(), indent=2))
        return 0
    
    # ========================================================
    # AUTHORIZATION CHECK
    # ========================================================
    config_dir = get_app_config_dir()
    
    # If setup is requested, allow it unconditionally
    if args.setup:
        setup_wizard(logger)
        return 0
    
    # Otherwise, check authorization before doing anything
    if not check_authorization_before_launch(config_dir):
        print(f"\n{CROSS} AUTHORIZATION FAILED")
        print(f"Authorization file: {config_dir / 'authorization.json'}")
        print("\nTo register this machine:")
        print(f"  python launcher.py --setup")
        logger.error("Authorization check failed - access denied")
        sys.exit(1)
    
    logger.info(f"{CHECK} Authorization check passed")
    
    # ========================================================
    # CONTINUE WITH NORMAL STARTUP
    # ========================================================
    
    # Load configuration
    config = load_config()
    
    # Check if setup is needed
    if "trading_platform" not in config or config["trading_platform"] is None:
        print(f"{INFO}  First-time setup required.\n")
        setup_wizard(logger)
        config = load_config()  # Reload config
    
    # Run the app
    success = run_app(logger, config)
    
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())
