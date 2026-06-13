#!/usr/bin/env python3
"""
Launch script for the Futures Trading Bot Web Dashboard
"""


import os
import sys
import webbrowser
import time
import logging
from threading import Timer

# Tkinter for double launch
import tkinter as tk
from tkinter import simpledialog

# ============================================================================
# WINDOWS ENCODING FIX - Must be FIRST
# ============================================================================
import io
if sys.platform == 'win32':
    # Force UTF-8 encoding on Windows
    try:
        if sys.stdout.encoding != 'utf-8':
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        if sys.stderr.encoding != 'utf-8':
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except:
        pass


# NOW safe to import everything else
from debug_config import debug_print, production_print, SUPPRESS_WERKZEUG, DEBUG, TERRA, ROCKET, CHECK, WRENCH, CROSS, WARNING, FOLDER, BULB


# ============================================================================
# SUPPRESS LOGS
# ============================================================================
if SUPPRESS_WERKZEUG:
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    logging.getLogger('flask.app').setLevel(logging.ERROR)


# ============================================================================
# CHROME LAUNCHER
# ============================================================================


def ensure_chrome_running():
    """
    Ensure Chrome is running with remote debugging.
    Uses chrome_helper.py if available, otherwise tries manual launch.
    
    Returns:
        True if Chrome is running or launched successfully
    """
    try:
        # Try using chrome_helper module
        import chrome_helper 
        return chrome_helper.ensure_chrome_running(port=9222)
    
    except Exception as e:
        # Fallback: manual check
        debug_print(f"{WARNING}  chrome_helper failed: {e}")
        
        try:
            import requests
            # Check if Chrome is already running
            response = requests.get("http://localhost:9222/json/version", timeout=2)
            if response.status_code == 200:
                production_print("✓ Chrome already running on port 9222")
                return True
        except:
            pass
        
        # Chrome not running - try to launch it
        production_print(f"{CROSS} Chrome not running and auto-launch failed")
        
        return False


# ============================================================================
# MAIN
# ============================================================================

# Port is set after instance selection in main()
# port = int(os.getenv("PORT", "5050"))
_DEFAULT_PORT = 5050



def open_browser(p=_DEFAULT_PORT):
    """Open the web browser to the dashboard URL."""
    url = f"http://localhost:{p}"
    production_print(f"{TERRA} Opening web browser to: {url}")
    webbrowser.open(url)

def pick_instance():
   """Show instance picker dialog. Returns (instance_id, symbol, port)."""
   try:
       # Tkinter path — works on Windows and most Mac installs
       result = {'choice': 1}

       root = tk.Tk()
       root.title("Trading Bot Launcher")
       root.geometry("380x190")
       root.resizable(False, False)
       root.configure(bg='#0d1117')
       try:
           root.eval('tk::PlaceWindow . center')
       except Exception:
           pass

       tk.Label(
           root, text="Select Bot Instance to Start:",
           font=('Segoe UI', 12, 'bold'),
           bg='#0d1117', fg='#f0f6fc', pady=16
       ).pack()

       btn_frame = tk.Frame(root, bg='#0d1117')
       btn_frame.pack(pady=8)

       def choose(n):
           result['choice'] = n
           root.destroy()

       tk.Button(
           btn_frame, text="Bot 1 — MES / ES\nport 5050",
           command=lambda: choose(1),
           bg='#238636', fg='white', font=('Segoe UI', 10, 'bold'),
           padx=18, pady=10, relief='flat', cursor='hand2'
       ).pack(side='left', padx=10)

       tk.Button(
           btn_frame, text="Bot 2 — NQ / MNQ\nport 5051",
           command=lambda: choose(2),
           bg='#1f6feb', fg='white', font=('Segoe UI', 10, 'bold'),
           padx=18, pady=10, relief='flat', cursor='hand2'
       ).pack(side='left', padx=10)

       root.mainloop()
       n = result['choice']

   except Exception:
       # Tkinter unavailable (older Mac dev machine) — CLI fallback
       print("\n--- Trading Bot Launcher ---")
       print("1: MES/ES Bot (port 5050)")
       print("2: NQ/MNQ Bot (port 5051)")
       try:
           raw = input("Select instance (1 or 2, default=1): ").strip()
           n = int(raw) if raw in ('1', '2') else 1
       except Exception:
           n = 1

   symbol = 'MES' if n == 1 else 'MNQ'
   port_num = 4999 + n  # 1→5050, 2→5051
   return n, symbol, port_num



def main():
    production_print(f"{ROCKET} Launching Futures Trading Bot Web Dashboard...")


    if DEBUG:
        production_print("=" * 60)

    # ========================================================================
    # INSTANCE SELECTION — must happen before importing web_app
    # ========================================================================
    instance_id, instance_symbol, port = pick_instance()
    os.environ['BOT_INSTANCE'] = str(instance_id)
    os.environ['PORT'] = str(port)
    os.environ['DATABASE_PATH'] = os.getenv(
        'DATABASE_PATH',
        os.path.join('data', 'db', f'market_data_bot{instance_id}.db')
    )
    production_print(f"{CHECK} Instance {instance_id} selected: {instance_symbol} on port {port}")

    
    # Change to the script directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    
    debug_print(f"{FOLDER} Working directory: {script_dir}")
    
    # ========================================================================
    # LAUNCH CHROME (NEW!)
    # ========================================================================
    production_print(f"{TERRA} Checking Chrome remote debugging...")
    
    if not ensure_chrome_running():
        print("\n" + "="*60)
        print(f"{WARNING}  WARNING: Chrome not running")
        print("="*60)
        print("\nThe trading bot needs Chrome with remote debugging enabled.")
        print("\nYou can:")
        print("  1. Start Chrome manually (see documentation)")
        print("  2. Install chrome_helper.py for automatic launching")
        print("\nContinuing anyway - some features may not work.")
        print("="*60 + "\n")
        
        # Don't exit - continue anyway for testing
        time.sleep(2)
    
    # ========================================================================
    # START FLASK
    # ========================================================================
    production_print(f"{WRENCH} Starting Flask web server...")
    
    # Schedule browser opening after 3 seconds
    if os.environ.get('LAUNCHED_BY_LAUNCHER') != '1':
        Timer(3.0, lambda: open_browser(port)).start()
    
    # Import and run the Flask app
    try:
        from web_app import app
        debug_print(f"{CHECK} Flask app loaded successfully")
        debug_print(f"{TERRA} Dashboard will be available at: http://localhost:5050")
        debug_print(f"{WRENCH} Use Ctrl+C to stop the web server")
        if DEBUG:
            debug_print("=" * 60)
        
        # Run the Flask app
        app.run(host='0.0.0.0', port=port, debug=DEBUG)
        
    except ImportError as e:
        print(f"{TERRA} Error importing Flask app: {e}")
        print(f"{BULB} Make sure you have installed the required dependencies:")
        print("   pip install flask pandas numpy requests python-dotenv matplotlib")
        sys.exit(1)
    except Exception as e:
        print(f"{CROSS} Error starting web server: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()



