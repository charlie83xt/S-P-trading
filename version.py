"""
Version and update management for S-P Trading App.
"""

import json
import os
from pathlib import Path
from typing import Optional, Dict, Any

# Current app version
APP_VERSION = "0.1.15"
APP_NAME = "S-P Trading"

# Version file location (inside app config directory)
def get_version_file():
    """Get path to stored version file."""
    config_dir = get_app_config_dir()
    return config_dir / "version.json"

def get_app_config_dir() -> Path:
    """Get platform-specific app config directory."""
    import platform
    system = platform.system()
    
    if system == "Darwin":  # macOS
        base = Path.home() / "Library" / "Application Support"
    elif system == "Windows":
        base = Path(os.getenv("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:  # Linux
        base = Path.home() / ".config"
    
    app_dir = base / "S-P-Trading"
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir

def load_version_info() -> Dict[str, Any]:
    """Load version and update info from disk."""
    version_file = get_version_file()
    
    if version_file.exists():
        try:
            with open(version_file, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    
    # Default version info
    return {
        "version": APP_VERSION,
        "installed_at": None,
        "last_checked_update": None,
        "update_available": False,
        "latest_version": APP_VERSION
    }

def save_version_info(info: Dict[str, Any]):
    """Save version info to disk."""
    version_file = get_version_file()
    with open(version_file, 'w') as f:
        json.dump(info, f, indent=2)

def check_for_updates(check_server: Optional[str] = None) -> Dict[str, Any]:
    """
    Check for available updates.
    
    Args:
        check_server: Optional URL to check for updates
        
    Returns:
        Dict with update info
    """
    info = load_version_info()
    
    # If no server specified, check is skipped
    if not check_server:
        return info
    
    # TODO: Implement server-based update check
    # For now, just return current info
    import time
    info["last_checked_update"] = time.time()
    save_version_info(info)
    
    return info

def is_update_available() -> bool:
    """Check if an update is available."""
    info = load_version_info()
    return info.get("update_available", False)

def get_current_version() -> str:
    """Get current installed version."""
    return APP_VERSION

def get_latest_version() -> str:
    """Get latest available version."""
    info = load_version_info()
    return info.get("latest_version", APP_VERSION)
