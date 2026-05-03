"""
Main launcher for S-P Trading App.
Cross-platform startup that handles Chrome, dashboard, and authorization.

Usage:
    python launcher.py               # Run with default settings
    python launcher.py --setup       # First-time setup wizard
    python launcher.py --debug       # Debug mode (verbose logging)
    python launcher.py --machine-id  # Show machine ID (for license requests)
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

sys.path.insert(0, str(Path(__file__).parent))

from chrome_helper import launch_chrome, wait_for_chrome, kill_chrome_on_port
from app_config import (
    load_config, save_config, get_config_value, set_config_value,
    load_env_file, save_env_file, get_log_dir, get_app_config_dir
)
from version import APP_VERSION, load_version_info
from authorization import (
    check_authorization_before_launch, register_machine,
    AuthorizationManager, LicenseManager, MachineFingerprint,
    LICENSE_TYPES
)

# ============================================================================
# LOGGING
# ============================================================================

def setup_logging(debug: bool = False):
    log_dir  = get_log_dir()
    log_file = log_dir / f"launcher_{time.strftime('%Y%m%d_%H%M%S')}.log"
    level    = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)


# ============================================================================
# HEADER
# ============================================================================

def print_header():
    print("\n" + "=" * 60)
    print(f"{BOT} S-P TRADING APP")
    print(f"Version: {APP_VERSION}")
    print("=" * 60 + "\n")


# ============================================================================
# INSTALLATION VALIDATION
# ============================================================================

def validate_installation() -> bool:
    logger = logging.getLogger(__name__)
    if getattr(sys, 'frozen', False):
        try:
            import trading_bot, web_app, config
            logger.info("[OK] Core modules loaded successfully")
            return True
        except ImportError as e:
            logger.error(f"[X] Failed to import module: {e}")
            return False
    else:
        for file in ["trading_bot.py", "config.py", "launch_web_dashboard.py"]:
            if not Path(file).exists():
                logger.error(f"[X] Missing required file: {file}")
                return False
        logger.info("[OK] Installation validation passed")
        return True


# ============================================================================
# LICENSE / AUTHORIZATION
# ============================================================================

def _show_license_menu(logger, config_dir, machine_fingerprint, license_manager):
    machine_id = machine_fingerprint[:4].upper()
    print("\n" + "=" * 60)
    print(f"{CROSS} LICENSE REQUIRED")
    print("=" * 60)
    print(f"\nMachine ID: {machine_id}")
    print("\nOptions:")
    print("  1) Start free 14-day trial (no key needed)")
    print("  2) Enter license key (if you purchased one)")
    print("  3) Show machine ID (to request a key from developer)")
    print("  4) Exit")
    print()

    choice = input("Enter choice (1-4): ").strip()

    if choice == "1":
        key = license_manager.generate_trial(machine_fingerprint)
        print(f"\n{CHECK} 14-day trial activated!")
        print(f"   Key: {key}")
        print("   The trial starts now. Upgrade any time to continue after it expires.\n")
        return True

    elif choice == "2":
        print("\nYou need the license key AND the expiry string from your purchase email.")
        key_input    = input("License key  (SP-XXXX-XXXX-XXXX-XXXX): ").strip()
        expiry_input = input("Expiry string (YYYYMMDD or 'none' for lifetime): ").strip()
        email_input  = input("Your email (optional, press Enter to skip): ").strip() or None
        result = license_manager.activate(
            key_input, machine_fingerprint,
            user_email=email_input,
            expiry_str=expiry_input if expiry_input else None,
        )
        if result["valid"]:
            print(f"\n{CHECK} License activated — {result.get('label', '')} plan")
            if result.get("days_remaining") is not None:
                print(f"   Expires in {result['days_remaining']} days")
            else:
                print("   Lifetime license — never expires")
            return True
        else:
            print(f"\n{CROSS} Activation failed: {result['error']}")
            return False

    elif choice == "3":
        print(f"\n{NOTE} Your Machine ID: {machine_id}")
        print("Send this to the developer along with your payment confirmation.\n")
        input("Press Enter to continue...")
        return _show_license_menu(logger, config_dir, machine_fingerprint, license_manager)

    else:
        return False


def check_license(logger, config_dir: Path) -> bool:
    """License gate — defers to web UI for first-run activation."""
    lic_mgr     = LicenseManager(config_dir)
    fingerprint = MachineFingerprint.generate_fingerprint()
    result      = lic_mgr.check_license_valid(fingerprint)

    if not result["valid"]:
        logger.info("No valid license — first run setup will handle activation")
        first_run_marker = config_dir / "first_run"
        first_run_marker.touch()
    else:
        label = result.get("label", "")
        days  = result.get("days_remaining")
        print(f"{CHECK} License: {label}", end="")
        if days is None:
            print(" (Lifetime)")
        else:
            print(f" — {days} days remaining")
            if days <= 7:
                print(f"{WARNING} License expires soon!")

    return True


# ============================================================================
# SETUP WIZARD
# ============================================================================

def setup_wizard(logger):
    print("\n" + "=" * 60)
    print(f"{WRENCH} INITIAL SETUP")
    print("=" * 60 + "\n")

    config     = load_config()
    config_dir = get_app_config_dir()

    print(f"{NOTE} Step 1: Machine Registration")
    print("-" * 40)
    machine_id = MachineFingerprint.get_machine_id()
    print(f"Your Machine ID: {machine_id}")
    user_email = input("Enter your email address (for license tracking): ").strip()

    if not register_machine(config_dir, user_email):
        logger.error(f"{CROSS} Registration failed.")
        sys.exit(1)

    print(f"\n{NOTE} Step 2: Trading Configuration")
    print("-" * 40)
    print("Setting up Tradovate platform...")
    config["trading_platform"] = "tradovate_ui"

    symbol = input("\nDefault trading symbol (default: MES): ").strip() or "MES"
    config["default_symbol"] = symbol

    dry_run = input("Start in DRY-RUN mode? (yes/no, default: yes): ").strip().lower() != "no"
    config["dry_run"] = dry_run

    save_config(config)

    print(f"\n{NOTE} Enter your Tradovate credentials:")
    username = input("Tradovate username: ").strip()
    password = input("Tradovate password: ").strip()
    env_vars = load_env_file()
    env_vars["TRADOVATE_USERNAME"] = username
    env_vars["TRADOVATE_PASSWORD"] = password
    save_env_file(env_vars)

    logger.info(f"{CHECK} Setup wizard completed")
    print(f"\n{CHECK} Setup complete! You can now start the app.\n")


# ============================================================================
# CHROME
# ============================================================================

def start_chrome(logger, config: dict) -> bool:
    chrome_port = config.get("chrome_port", 9222)
    logger.info(f"{TERRA} Launching Chrome on port {chrome_port}...")
    try:
        kill_chrome_on_port(chrome_port)
        time.sleep(1)
    except Exception:
        pass

    chrome_process = launch_chrome(port=chrome_port)
    if not chrome_process:
        logger.error(f"{CROSS} Failed to launch Chrome")
        return False

    if not wait_for_chrome(port=chrome_port, timeout=10):
        logger.error(f"{CROSS} Chrome failed to respond")
        chrome_process.terminate()
        return False

    logger.info(f"{CHECK} Chrome ready")
    return True


# ============================================================================
# DASHBOARD
# ============================================================================

def start_dashboard(logger, config: dict) -> bool:
    dashboard_port = config.get("dashboard_port", 5000)
    logger.info(f"{CHART} Starting dashboard on port {dashboard_port}...")

    try:
        if getattr(sys, 'frozen', False):
            def run_flask():
                try:
                    os.environ['PW_MODE']      = 'cdp'
                    os.environ['BROWSER_MODE'] = 'cdp'
                    os.environ['CDP_PORT']     = '9222'
                    os.environ['CDP_URL']      = 'http://localhost:9222'
                    os.environ['PORT']         = str(dashboard_port)
                    os.environ['LAUNCHED_BY_LAUNCHER'] = '1'
                    logger.info("Environment set: PW_MODE=cdp, CDP_PORT=9222")
                    import web_app
                    web_app.app.run(
                        host='0.0.0.0',
                        port=dashboard_port,
                        debug=False,
                        use_reloader=False,
                    )
                except Exception as e:
                    logger.error(f"Flask error: {e}")
                    import traceback
                    traceback.print_exc()

            flask_thread = Thread(target=run_flask, daemon=True)
            flask_thread.start()
            time.sleep(3)
            logger.info(f"{CHECK} Dashboard started in background thread")
            return True

        else:
            process = subprocess.Popen([sys.executable, "launch_web_dashboard.py"])
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


# ============================================================================
# MAIN RUN LOOP
# ============================================================================

def run_app(logger, config: dict):
    print("\n" + "=" * 60)
    print(f"{ROCKET} STARTING APPLICATION")
    print("=" * 60 + "\n")

    if not start_chrome(logger, config):
        print(f"{CROSS} Failed to start Chrome.")
        return False

    if not start_dashboard(logger, config):
        print(f"{CROSS} Failed to start dashboard.")
        return False

    dashboard_port = config.get('dashboard_port', 5000)
    dashboard_url  = f"http://localhost:{dashboard_port}"

    try:
        time.sleep(2)
        # ── FIXED: is_first_run() called with parentheses ──────────────────
        from first_run import is_first_run
        startup_url = f"http://localhost:{dashboard_port}/setup" if is_first_run() else dashboard_url
        webbrowser.open(startup_url)
        logger.info(f"{CHECK} Browser opened to {startup_url}")
    except Exception as e:
        logger.warning(f"Could not auto-open browser: {e}")
        logger.info(f"Please open manually: {dashboard_url}")

    env_vars = load_env_file()
    os.environ.update(env_vars)

    print("\n" + "=" * 60)
    print(f"{CHECK} APPLICATION RUNNING")
    print("=" * 60)
    print(f"Dashboard : {dashboard_url}")
    print(f"Chrome CDP: localhost:{config.get('chrome_port', 9222)}")
    print("\nPress Ctrl+C to stop.\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print(f"\n\n{CROSS} Shutting down...")
        logger.info("Application stopped by user")

    return True


# ============================================================================
# ENTRY POINT
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='S-P Trading Application Launcher',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python launcher.py               Run the app
  python launcher.py --setup       Run setup wizard
  python launcher.py --debug       Enable debug logging
  python launcher.py --machine-id  Show machine ID (to request a license)
        """
    )
    parser.add_argument('--setup',      action='store_true', help='Run setup wizard')
    parser.add_argument('--debug',      action='store_true', help='Enable debug logging')
    parser.add_argument('--version',    action='store_true', help='Show version')
    parser.add_argument('--auth-info',  action='store_true', help='Show authorization info')
    parser.add_argument('--machine-id', action='store_true', help="Show this machine's license ID")

    args   = parser.parse_args()
    logger = setup_logging(debug=args.debug)
    print_header()

    config_dir = get_app_config_dir()

    # ── Quick info flags ──────────────────────────────────────────────────────
    if args.version:
        print(f"Version: {APP_VERSION}")
        return 0

    if args.machine_id:
        mid = MachineFingerprint.get_machine_id()
        print(f"\n{NOTE} Your Machine ID: {mid}")
        print("Send this to the developer to receive your license key.\n")
        return 0

    if args.auth_info:
        import json
        auth = AuthorizationManager(config_dir)
        print(json.dumps(auth.get_authorization_info(), indent=2))
        return 0

    if args.setup:
        setup_wizard(logger)
        return 0

    # ── AUTO-UPDATE CHECK ─────────────────────────────────────────────────────
    # Runs in a background thread — never blocks or slows startup.
    # On first run this will find nothing (v0.1.0 is latest).
    # On subsequent runs it will detect newer GitHub releases automatically.
    try:
        from update_manager import check_and_apply_updates
        if getattr(sys, 'frozen', False):
            # Packaged app: _MEIPASS is the _internal folder
            # Go one level up to reach the actual app root where .py files live
            app_dir = Path(sys._MEIPASS).parent
        else:
            # Development: project root
            app_dir = Path(__file__).parent
        check_and_apply_updates(app_dir, auto_update=False, background=True)
        logger.info("Update check started in background")
    except Exception as e:
        logger.warning(f"Update check could not start: {e}")

    # ── LICENSE CHECK ─────────────────────────────────────────────────────────
    check_license(logger, config_dir)
    logger.info(f"{CHECK} Authorization check passed")

    # ── LOAD CONFIG & LAUNCH ──────────────────────────────────────────────────
    config = load_config()

    if "trading_platform" not in config or config["trading_platform"] is None:
        print(f"{INFO}  First-time setup required.\n")
        setup_wizard(logger)
        config = load_config()

    success = run_app(logger, config)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
