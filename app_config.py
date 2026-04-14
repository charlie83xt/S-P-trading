"""
Application configuration management for shipped S-P Trading app.
Handles config storage in OS-appropriate locations.
"""

import os
import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

def get_app_config_dir(app_name: str = "S-P-Trading") -> Path:
    """
    Get platform-specific app config directory.
    
    Returns:
        Path to app config directory (created if not exists)
    """
    import platform
    system = platform.system()
    
    if system == "Darwin":  # macOS
        base = Path.home() / "Library" / "Application Support"
    elif system == "Windows":
        base = Path(os.getenv("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:  # Linux
        base = Path.home() / ".config"
    
    app_dir = base / app_name
    app_dir.mkdir(parents=True, exist_ok=True)
    
    logger.debug(f"Config dir: {app_dir}")
    return app_dir

def get_config_file(app_name: str = "S-P-Trading") -> Path:
    """Get path to main config file."""
    config_dir = get_app_config_dir(app_name)
    return config_dir / "app_config.json"

def get_env_file(app_name: str = "S-P-Trading") -> Path:
    """Get path to .env file (for trading credentials)."""
    config_dir = get_app_config_dir(app_name)
    return config_dir / ".env"

def load_config() -> Dict[str, Any]:
    """
    Load application configuration from disk.
    
    Returns:
        Config dictionary
    """
    config_file = get_config_file()
    
    if config_file.exists():
        try:
            with open(config_file, 'r') as f:
                config = json.load(f)
                logger.info(f"✅ Loaded config from {config_file}")
                return config
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
    
    # Return default config if file doesn't exist
    return get_default_config()

def save_config(config: Dict[str, Any]):
    """
    Save configuration to disk.
    
    Args:
        config: Configuration dictionary
    """
    config_file = get_config_file()
    
    try:
        with open(config_file, 'w') as f:
            json.dump(config, f, indent=2)
        logger.info(f"✅ Saved config to {config_file}")
    except Exception as e:
        logger.error(f"Failed to save config: {e}")

def get_default_config() -> Dict[str, Any]:
    """Get default application configuration."""
    return {
        "version": "0.1.0",
        "trading_platform": "tradovate_ui",
        "default_symbol": "MES",
        "dry_run": True,
        "chrome_port": 9222,
        "dashboard_port": 5000,
        "auto_update_check": True,
        "update_check_interval": 86400,  # 24 hours
    }

def get_config_value(key: str, default: Any = None) -> Any:
    """
    Get single config value.
    
    Args:
        key: Config key (supports dot notation like "trading.platform")
        default: Default value if key not found
        
    Returns:
        Config value or default
    """
    config = load_config()
    
    # Support nested keys with dot notation
    keys = key.split('.')
    value = config
    for k in keys:
        if isinstance(value, dict):
            value = value.get(k)
        else:
            return default
    
    return value if value is not None else default

def set_config_value(key: str, value: Any):
    """
    Set single config value.
    
    Args:
        key: Config key (supports dot notation)
        value: Value to set
    """
    config = load_config()
    
    # Support nested keys with dot notation
    keys = key.split('.')
    target = config
    
    for k in keys[:-1]:
        if k not in target:
            target[k] = {}
        target = target[k]
    
    target[keys[-1]] = value
    save_config(config)

def load_env_file() -> Dict[str, str]:
    """
    Load environment variables from .env file.
    
    Returns:
        Dictionary of environment variables
    """
    env_file = get_env_file()
    env_vars = {}
    
    if env_file.exists():
        try:
            import dotenv
            env_vars = dotenv.dotenv_values(env_file)
            logger.info(f"✅ Loaded .env from {env_file}")
        except ImportError:
            # Fallback: parse manually if dotenv not available
            with open(env_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    if '=' in line:
                        key, val = line.split('=', 1)
                        env_vars[key.strip()] = val.strip().strip('"\'')
    
    return env_vars

def save_env_file(env_vars: Dict[str, str]):
    """
    Save environment variables to .env file.
    
    Args:
        env_vars: Dictionary of environment variables
    """
    env_file = get_env_file()
    
    try:
        with open(env_file, 'w') as f:
            for key, value in env_vars.items():
                # Quote values that contain spaces
                if ' ' in str(value):
                    f.write(f'{key}="{value}"\n')
                else:
                    f.write(f'{key}={value}\n')
        
        # Restrict file permissions (sensitive data)
        os.chmod(env_file, 0o600)
        logger.info(f"✅ Saved .env to {env_file}")
    except Exception as e:
        logger.error(f"Failed to save .env: {e}")

def get_log_dir(app_name: str = "S-P-Trading") -> Path:
    """
    Get directory for application logs.
    
    Returns:
        Path to log directory
    """
    config_dir = get_app_config_dir(app_name)
    log_dir = config_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir

def get_data_dir(app_name: str = "S-P-Trading") -> Path:
    """
    Get directory for application data (databases, trades history, etc).
    
    Returns:
        Path to data directory
    """
    config_dir = get_app_config_dir(app_name)
    data_dir = config_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir
