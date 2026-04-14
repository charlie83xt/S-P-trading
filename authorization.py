"""
AUTHORIZATION SYSTEM for S-P Trading

Handles user licensing and machine-based verification.
Options: License keys, server validation, or machine fingerprinting.
"""

import hashlib
import json
import uuid
import platform
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


# ============================================================================
# OPTION 1: MACHINE FINGERPRINTING
# ============================================================================

class MachineFingerprint:
    """Generate and verify machine fingerprints for license binding."""
    
    @staticmethod
    def get_mac_address() -> str:
        """Get primary network MAC address."""
        try:
            mac = uuid.getnode()
            return str(mac)
        except Exception as e:
            logger.warning(f"Failed to get MAC: {e}")
            return "unknown"
    
    @staticmethod
    def get_hostname() -> str:
        """Get machine hostname."""
        try:
            import socket
            return socket.gethostname()
        except Exception as e:
            logger.warning(f"Failed to get hostname: {e}")
            return "unknown"
    
    @staticmethod
    def get_disk_id() -> str:
        """Get disk serial number (platform-specific)."""
        try:
            system = platform.system()
            
            if system == "Darwin":  # macOS
                result = subprocess.run(
                    ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                for line in result.stdout.split('\n'):
                    if "IOPlatformSerialNumber" in line:
                        return line.split('"')[-2]
            
            elif system == "Windows":
                result = subprocess.run(
                    ["wmic", "logicaldisk", "get", "serialnumber"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                lines = result.stdout.strip().split('\n')
                if len(lines) > 1:
                    return lines[1].strip()
            
            else:  # Linux
                result = subprocess.run(
                    ["lsblk", "-d", "-o", "SERIAL"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                lines = result.stdout.strip().split('\n')
                if len(lines) > 1:
                    return lines[1].strip()
        
        except Exception as e:
            logger.warning(f"Failed to get disk ID: {e}")
        
        return "unknown"
    
    @staticmethod
    def generate_fingerprint() -> str:
        """Generate a unique machine fingerprint."""
        mac = MachineFingerprint.get_mac_address()
        hostname = MachineFingerprint.get_hostname()
        disk = MachineFingerprint.get_disk_id()
        
        combined = f"{mac}:{hostname}:{disk}"
        fingerprint = hashlib.sha256(combined.encode()).hexdigest()
        
        logger.info(f"Generated fingerprint: {fingerprint[:16]}...")
        return fingerprint
    
    @staticmethod
    def verify_fingerprint(stored: str) -> bool:
        """Verify current machine matches stored fingerprint."""
        current = MachineFingerprint.generate_fingerprint()
        matches = current == stored
        
        if not matches:
            logger.warning("Machine fingerprint mismatch!")
        
        return matches


# ============================================================================
# OPTION 2: LICENSE KEY SYSTEM
# ============================================================================

class LicenseKey:
    """Generate and verify license keys."""
    
    # Simple format: EMAIL-RANDOM-CHECKSUM
    # Example: user@example.com-A1B2C3D4E5-F6G7H8I9J0
    
    SECRET_KEY = "sp-trading-license-secret"  # TODO: Keep this secure!
    
    @staticmethod
    def generate_license(user_email: str) -> str:
        """Generate a license key for a user."""
        # Generate random component
        random_part = str(uuid.uuid4()).split('-')[0].upper()
        
        # Create signature
        data = f"{user_email}:{random_part}"
        signature = hashlib.sha256(
            f"{data}:{LicenseKey.SECRET_KEY}".encode()
        ).hexdigest()[:10].upper()
        
        # Format: email-random-signature
        license_key = f"{user_email}-{random_part}-{signature}"
        
        logger.info(f"Generated license for {user_email}")
        return license_key
    
    @staticmethod
    def verify_license(license_key: str) -> bool:
        """Verify a license key is valid."""
        try:
            parts = license_key.split('-')
            if len(parts) < 3:
                return False
            
            # Reconstruct and verify signature
            email_parts = parts[:-2]  # All but last 2 parts
            user_email = '-'.join(email_parts)
            random_part = parts[-2]
            provided_sig = parts[-1]
            
            data = f"{user_email}:{random_part}"
            expected_sig = hashlib.sha256(
                f"{data}:{LicenseKey.SECRET_KEY}".encode()
            ).hexdigest()[:10].upper()
            
            return provided_sig == expected_sig
        
        except Exception as e:
            logger.error(f"License verification error: {e}")
            return False


# ============================================================================
# OPTION 3: SERVER-BASED VALIDATION
# ============================================================================

class ServerAuth:
    """Validate user via remote server (future implementation)."""
    
    AUTH_SERVER = "https://auth.sp-trading.app"  # TODO: Deploy this
    
    @staticmethod
    def validate_user(username: str, token: str) -> bool:
        """Validate user with server."""
        try:
            import requests
            
            response = requests.post(
                f"{ServerAuth.AUTH_SERVER}/validate",
                json={"username": username, "token": token},
                timeout=5
            )
            
            return response.status_code == 200
        
        except Exception as e:
            logger.error(f"Server validation error: {e}")
            # For now, fail open (allow offline use)
            # TODO: If offline too long, restrict features
            return True


# ============================================================================
# UNIFIED AUTHORIZATION MANAGER
# ============================================================================

class AuthorizationManager:
    """Main authorization interface - choose strategy below."""
    
    STRATEGY = "machine"  # Options: "machine", "license", "server"
    
    def __init__(self, config_dir: Path):
        """Initialize authorization manager."""
        self.config_dir = config_dir
        self.auth_file = config_dir / "authorization.json"
    
    def check_authorization(self) -> bool:
        """Check if user is authorized to run the app."""
        
        if self.STRATEGY == "machine":
            return self._check_machine_auth()
        
        elif self.STRATEGY == "license":
            return self._check_license_auth()
        
        elif self.STRATEGY == "server":
            return self._check_server_auth()
        
        else:
            logger.warning("Unknown auth strategy, allowing access")
            return True
    
    def _check_machine_auth(self) -> bool:
        """Verify machine fingerprint."""
        if not self.auth_file.exists():
            logger.warning("No authorization file. First-time setup.")
            return True  # First time - allow setup
        
        try:
            with open(self.auth_file) as f:
                auth_data = json.load(f)
            
            stored_fingerprint = auth_data.get("fingerprint")
            if not stored_fingerprint:
                logger.error("No fingerprint in auth file")
                return False
            
            return MachineFingerprint.verify_fingerprint(stored_fingerprint)
        
        except Exception as e:
            logger.error(f"Machine auth error: {e}")
            return False
    
    def _check_license_auth(self) -> bool:
        """Verify license key."""
        if not self.auth_file.exists():
            logger.warning("No license file. First-time setup.")
            return True
        
        try:
            with open(self.auth_file) as f:
                auth_data = json.load(f)
            
            license_key = auth_data.get("license")
            if not license_key:
                logger.error("No license in auth file")
                return False
            
            is_valid = LicenseKey.verify_license(license_key)
            
            if not is_valid:
                logger.error("Invalid license key")
            
            return is_valid
        
        except Exception as e:
            logger.error(f"License auth error: {e}")
            return False
    
    def _check_server_auth(self) -> bool:
        """Verify with server."""
        if not self.auth_file.exists():
            logger.warning("No auth file. First-time setup.")
            return True
        
        try:
            with open(self.auth_file) as f:
                auth_data = json.load(f)
            
            username = auth_data.get("username")
            token = auth_data.get("token")
            
            if not username or not token:
                logger.error("No credentials in auth file")
                return False
            
            return ServerAuth.validate_user(username, token)
        
        except Exception as e:
            logger.error(f"Server auth error: {e}")
            return False
    
    def register_authorization(self, user_email: Optional[str] = None) -> bool:
        """Register this machine/user for authorization."""
        
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            
            auth_data = {
                "created": datetime.now().isoformat(),
                "strategy": self.STRATEGY,
            }
            
            if self.STRATEGY == "machine":
                auth_data["fingerprint"] = MachineFingerprint.generate_fingerprint()
                auth_data["hostname"] = MachineFingerprint.get_hostname()
            
            elif self.STRATEGY == "license":
                if not user_email:
                    raise ValueError("user_email required for license strategy")
                auth_data["license"] = LicenseKey.generate_license(user_email)
                auth_data["email"] = user_email
            
            elif self.STRATEGY == "server":
                if not user_email:
                    raise ValueError("user_email required for server strategy")
                auth_data["username"] = user_email
                # Token would be obtained from login endpoint
                auth_data["token"] = "placeholder"
            
            # Write with restricted permissions
            with open(self.auth_file, 'w') as f:
                json.dump(auth_data, f, indent=2)
            
            # Make file readable only by owner (Unix-like)
            try:
                self.auth_file.chmod(0o600)
            except:
                pass
            
            logger.info("Authorization registered successfully")
            return True
        
        except Exception as e:
            logger.error(f"Authorization registration error: {e}")
            return False
    
    def get_authorization_info(self) -> Dict[str, Any]:
        """Get current authorization info."""
        if not self.auth_file.exists():
            return {"status": "not_authorized"}
        
        try:
            with open(self.auth_file) as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error reading auth info: {e}")
            return {"status": "error", "message": str(e)}


# ============================================================================
# INTEGRATION WITH LAUNCHER
# ============================================================================

def check_authorization_before_launch(config_dir: Path) -> bool:
    """
    Call this from launcher.py before starting the main app.
    
    Returns True if authorized, False if blocked.
    """
    auth = AuthorizationManager(config_dir)
    
    if not auth.check_authorization():
        print("❌ This machine is not authorized to run S-P Trading")
        print("Contact your administrator for a license key")
        return False
    
    return True


def register_machine(config_dir: Path, user_email: Optional[str] = None) -> bool:
    """
    Call this from launcher.py during first-time setup.
    
    user_email is required for license and server strategies.
    """
    auth = AuthorizationManager(config_dir)
    
    print("📝 Registering this machine for S-P Trading...")
    
    if auth.STRATEGY == "machine":
        print("Using machine fingerprint for authorization")
    elif auth.STRATEGY == "license":
        if not user_email:
            user_email = input("Enter your email address: ").strip()
    elif auth.STRATEGY == "server":
        if not user_email:
            user_email = input("Enter your username: ").strip()
    
    if auth.register_authorization(user_email):
        print("✅ Machine registration successful!")
        return True
    else:
        print("❌ Registration failed")
        return False


if __name__ == "__main__":
    # Example usage
    from pathlib import Path
    
    test_dir = Path.home() / ".sp-trading-test"
    test_dir.mkdir(exist_ok=True)
    
    # Test fingerprinting
    print("=== Machine Fingerprint ===")
    fp = MachineFingerprint.generate_fingerprint()
    print(f"Fingerprint: {fp}")
    print(f"Verified: {MachineFingerprint.verify_fingerprint(fp)}\n")
    
    # Test license key
    print("=== License Key ===")
    license_key = LicenseKey.generate_license("user@example.com")
    print(f"License: {license_key}")
    print(f"Valid: {LicenseKey.verify_license(license_key)}\n")
    
    # Test authorization manager
    print("=== Authorization Manager ===")
    auth = AuthorizationManager(test_dir)
    print(f"Auth file: {auth.auth_file}")
    print(f"Strategy: {auth.STRATEGY}")
    
    # Register and check
    register_machine(test_dir, "test@example.com")
    print(f"Authorized: {check_authorization_before_launch(test_dir)}")
    print(f"Auth info: {auth.get_authorization_info()}")