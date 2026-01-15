#!/usr/bin/env python3
"""
Launch script for the Futures Trading Bot Web Dashboard
"""

import os
import sys
import webbrowser
import time
from threading import Timer

port = int(os.getenv("PORT", "5050"))
def open_browser():
    """Open the web browser to the dashboard URL."""
    url = f"http://localhost:{port}"
    print(f"🌐 Opening web browser to: {url}")
    webbrowser.open(url)

def main():
    print("🚀 Launching Futures Trading Bot Web Dashboard...")
    print("=" * 60)
    
    # Change to the script directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    
    print(f"📁 Working directory: {script_dir}")
    print("🔧 Starting Flask web server...")
    
    # Schedule browser opening after 3 seconds
    Timer(3.0, open_browser).start()
    
    # Import and run the Flask app
    try:
        from web_app import app
        print("✅ Flask app loaded successfully")
        print("🌐 Dashboard will be available at: http://localhost:5050")
        print("🔧 Use Ctrl+C to stop the web server")
        print("=" * 60)
        
        # Run the Flask app
        app.run(host='0.0.0.0', port=port, debug=False)
        
    except ImportError as e:
        print(f"❌ Error importing Flask app: {e}")
        print("💡 Make sure you have installed the required dependencies:")
        print("   pip install flask pandas numpy requests python-dotenv matplotlib")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error starting web server: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()

