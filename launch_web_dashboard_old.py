#!/usr/bin/env python3
"""
Launch script for the Futures Trading Bot Web Dashboard
"""

import os
import sys
import webbrowser
import time
from threading import Timer
import logging
from debug_config import debug_print, production_print, SUPPRESS_WERKZEUG, DEBUG, TERRA, ROCKET, CHECK, WRENCH, CROSS, WARNING, FOLDER

if SUPPRESS_WERKZEUG:
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    logging.getLogger('flask.app').setLevel(logging.ERROR)


port = int(os.getenv("PORT", "5050"))
def open_browser():
    """Open the web browser to the dashboard URL."""
    url = f"http://localhost:{port}"
    production_print(f"{TERRA} Opening web browser to: {url}")
    webbrowser.open(url)

def main():
    production_print(f"{ROCKET} Launching Futures Trading Bot Web Dashboard...")

    if DEBUG:
        production_print("=" * 60)
    
    # Change to the script directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    
    debug_print(f"{FOLDER} Working directory: {script_dir}")
    production_print(f"{WRENCH} Starting Flask web server...")
    
    # Schedule browser opening after 3 seconds
    Timer(3.0, open_browser).start()
    
    # Import and run the Flask app
    try:
        from web_app import app
        debug_print(f"{CHECK} Flask app loaded successfully")
        debug_print(f"{TERRA} Dashboard will be available at: http://localhost:5050")
        debug_print(f"{WRENCH} Use Ctrl+C to stop the web server")
        if DEBUG:
            debug_print("=" * 60)
        
        # Run the Flask app
        app.run(host='0.0.0.0', port=port, debug=False)
        
    except ImportError as e:
        print(f"{CROSS} Error importing Flask app: {e}")
        print(f"{BULB} Make sure you have installed the required dependencies:")
        print("   pip install flask pandas numpy requests python-dotenv matplotlib")
        sys.exit(1)
    except Exception as e:
        print(f"{CROSS} Error starting web server: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()

