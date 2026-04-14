"""
Chrome remote debugging launcher for cross-platform support.
Handles OS-specific paths and startup arguments.
"""

import os
import platform
import subprocess
import time
import logging
from pathlib import Path
from typing import Optional, List

logger = logging.getLogger(__name__)

def get_chrome_executable_path() -> Optional[str]:
    """
    Find Chrome executable for the current OS.
    
    Returns:
        Path to Chrome executable, or None if not found
    """
    system = platform.system()
    
    if system == "Darwin":  # macOS
        paths = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
    elif system == "Windows":
        paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        ]
    else:  # Linux
        paths = [
            "/usr/bin/google-chrome",
            "/usr/bin/chromium-browser",
            "/usr/bin/chromium",
            "/snap/bin/chromium",
        ]
    
    for path in paths:
        expanded = os.path.expandvars(path)
        if os.path.isfile(expanded):
            logger.info(f"✅ Found Chrome at: {expanded}")
            return expanded
    
    logger.warning(f"❌ Chrome not found on {system}. Tried: {paths}")
    return None

def get_chrome_user_data_dir(app_name: str = "S-P-Trading") -> str:
    """
    Get platform-specific Chrome user data directory.
    
    Args:
        app_name: Application name for directory naming
        
    Returns:
        Path to Chrome user data directory
    """
    system = platform.system()
    
    if system == "Darwin":  # macOS
        base = Path.home() / "Library" / "Application Support"
    elif system == "Windows":
        base = Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:  # Linux
        base = Path.home() / ".local" / "share"
    
    chrome_dir = base / app_name / "chrome_profile"
    chrome_dir.mkdir(parents=True, exist_ok=True)
    
    return str(chrome_dir)

def launch_chrome(
    url: Optional[str] = None,
    port: int = 9222,
    headless: bool = False,
    app_name: str = "S-P-Trading"
) -> Optional[subprocess.Popen]:
    """
    Launch Chrome with remote debugging enabled.
    
    Args:
        url: Optional URL to open on startup
        port: Remote debugging port (default: 9222)
        headless: Whether to run headless (default: False)
        app_name: Application name for data directories
        
    Returns:
        Popen object for the Chrome process, or None if launch failed
    """
    chrome_path = get_chrome_executable_path()
    if not chrome_path:
        logger.error("Chrome not found on this system")
        return None
    
    user_data_dir = get_chrome_user_data_dir(app_name)
    
    # Build Chrome arguments
    args = [
        chrome_path,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    
    # Add optional URL
    if url:
        args.append(url)
    
    # Add headless flag if requested
    if headless:
        args.append("--headless")
    
    # Suppress output
    try:
        logger.info(f"🚀 Launching Chrome with args: {args[:3]}...")
        process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            preexec_fn=None if platform.system() == "Windows" else os.setsid
        )
        
        logger.info(f"✅ Chrome started (PID: {process.pid})")
        return process
        
    except Exception as e:
        logger.error(f"❌ Failed to launch Chrome: {e}")
        return None

def is_chrome_running(port: int = 9222) -> bool:
    """
    Check if Chrome is running on the specified port.
    
    Args:
        port: Debugging port to check
        
    Returns:
        True if Chrome is running and responding, False otherwise
    """
    try:
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(('127.0.0.1', port))
        sock.close()
        return result == 0
    except Exception:
        return False

def wait_for_chrome(port: int = 9222, timeout: int = 10) -> bool:
    """
    Wait for Chrome to start and respond on the debugging port.
    
    Args:
        port: Debugging port to check
        timeout: Timeout in seconds
        
    Returns:
        True if Chrome started successfully, False if timeout
    """
    start_time = time.time()
    while time.time() - start_time < timeout:
        if is_chrome_running(port):
            logger.info(f"✅ Chrome ready on port {port}")
            return True
        time.sleep(0.5)
    
    logger.warning(f"⚠️  Chrome not responding after {timeout}s")
    return False

def kill_chrome_on_port(port: int = 9222):
    """
    Kill Chrome process running on the specified port (cleanup utility).
    
    Args:
        port: Debugging port
    """
    import sys
    system = platform.system()
    
    try:
        if system == "Windows":
            # Windows: use taskkill
            subprocess.run(
                ["taskkill", "/F", "/IM", "chrome.exe"],
                capture_output=True
            )
        else:
            # macOS/Linux: use lsof and kill
            import subprocess
            result = subprocess.run(
                ["lsof", "-i", f":{port}"],
                capture_output=True,
                text=True
            )
            lines = result.stdout.strip().split('\n')[1:]  # Skip header
            for line in lines:
                parts = line.split()
                if len(parts) > 1:
                    pid = parts[1]
                    os.kill(int(pid), 9)
        
        logger.info(f"✅ Chrome process terminated")
    except Exception as e:
        logger.debug(f"Could not terminate Chrome: {e}")
