"""
AUTHORIZATION & LICENSING SYSTEM for S-P Trading


Handles machine fingerprinting, license key validation, trial management,
and expiry enforcement. Evolved from the original machine-auth-only system
to support full distribution licensing.


License key format: SP-{TYPE}-{MHASH}-{VAL1}-{VAL2}


  TYPE  = TRIA, BASI, PREM, LIFE
  MHASH = first 4 chars of machine fingerprint (machine-bound)
  VAL1  = first 4 chars of HMAC checksum
  VAL2  = last 4 chars of HMAC checksum


Example: SP-PREM-A7F2-8C4D-9E1B
"""


import hashlib
import hmac
import json
import uuid
import platform
import subprocess
import socket
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple
from debug_config import CHECK, CROSS, NOTE, WARNING


logger = logging.getLogger(__name__)


# ============================================================================
# SECRET KEY — CHANGE THIS BEFORE DISTRIBUTION, KEEP IT PRIVATE
# ============================================================================

_SECRET_KEY = "378cc84eefdf43cbc73a609984b75c93c49abf926a193a4cdf458eef6414467c"   # ← Replace with a strong random string


# ============================================================================
# LICENSE TYPES & FEATURES
# ============================================================================


LICENSE_TYPES = {
    "TRIA": {
        "label":         "Trial",
        "duration_days": 14,
        "max_positions": 1,
        "features":      ["basic_trading", "single_strategy"],
    },
    "BASI": {
        "label":         "Basic",
        "duration_days": 365,
        "max_positions": 3,
        "features":      ["basic_trading", "all_strategies"],
    },
    "PREM": {
        "label":         "Premium",
        "duration_days": 365,
        "max_positions": None,   # unlimited
        "features":      ["all"],
    },
    "LIFE": {
        "label":         "Lifetime",
        "duration_days": None,   # never expires
        "max_positions": None,
        "features":      ["all"],
    },
}


# ============================================================================
# MACHINE FINGERPRINTING  (unchanged from original, kept intact)
# ============================================================================

class MachineFingerprint:
    """Generate and verify machine fingerprints for license binding."""

    @staticmethod
    def get_mac_address() -> str:
        try:
            return str(uuid.getnode())
        except Exception as e:
            logger.warning(f"Failed to get MAC: {e}")
            return "unknown"


    @staticmethod
    def get_hostname() -> str:
        try:
            return socket.gethostname()
        except Exception as e:
            logger.warning(f"Failed to get hostname: {e}")
            return "unknown"


    @staticmethod
    def get_disk_id() -> str:
        try:
            system = platform.system()
            if system == "Darwin":
                result = subprocess.run(
                    ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                    capture_output=True, text=True, timeout=5
                )
                for line in result.stdout.split("\n"):
                    if "IOPlatformSerialNumber" in line:
                        return line.split('"')[-2]
            elif system == "Windows":
                result = subprocess.run(
                    ["wmic", "logicaldisk", "get", "serialnumber"],
                    capture_output=True, text=True, timeout=5
                )
                lines = result.stdout.strip().split("\n")
                if len(lines) > 1:
                    return lines[1].strip()
            else:
                result = subprocess.run(
                    ["lsblk", "-d", "-o", "SERIAL"],
                    capture_output=True, text=True, timeout=5
                )
                lines = result.stdout.strip().split("\n")
                if len(lines) > 1:
                    return lines[1].strip()
        except Exception as e:
            logger.warning(f"Failed to get disk ID: {e}")
        return "unknown"


    @staticmethod
    def generate_fingerprint() -> str:
        """Generate a unique, stable machine fingerprint (SHA-256 hex)."""
        mac      = MachineFingerprint.get_mac_address()
        hostname = MachineFingerprint.get_hostname()
        disk     = MachineFingerprint.get_disk_id()
        combined = f"{mac}:{hostname}:{disk}"
        fingerprint = hashlib.sha256(combined.encode()).hexdigest()
        logger.debug(f"Machine fingerprint: {fingerprint[:16]}...")
        return fingerprint


    @staticmethod
    def verify_fingerprint(stored: str) -> bool:
        """Verify current machine matches a stored fingerprint."""
        current = MachineFingerprint.generate_fingerprint()
        matches = current == stored
        if not matches:
            logger.warning("Machine fingerprint mismatch!")
        return matches


    @staticmethod
    def get_machine_id() -> str:
        """Short ID used in license keys (first 4 hex chars, uppercase)."""
        return MachineFingerprint.generate_fingerprint()[:4].upper()


# ============================================================================
# LICENSE KEY — GENERATION & VALIDATION
# ============================================================================


class LicenseKey:
    """
    Generate and validate machine-bound, expiry-aware license keys.


    Format: SP-{TYPE}-{MHASH}-{VAL1}-{VAL2}


    The checksum is an HMAC-SHA256 over
    "SP|{TYPE}|{MHASH}|{EXPIRY_STR}" using the secret key, so any
    tampering (changing type, machine hash, or expiry) invalidates it.
    """


    @staticmethod
    def _make_checksum(type_code: str, machine_hash: str, expiry_str: str) -> str:
        payload = f"SP|{type_code}|{machine_hash}|{expiry_str}"
        mac = hmac.new(
            _SECRET_KEY.encode(),
            payload.encode(),
            hashlib.sha256
        ).hexdigest()[:8].upper()
        return mac                 # 8 hex chars → split into two 4-char groups

    @staticmethod
    def generate(
        license_type: str,
        machine_fingerprint: str,
        duration_days: Optional[int] = None
    ) -> Tuple[str, str]:
        """
        Generate a license key.

        Args:
            license_type:        One of TRIA / BASI / PREM / LIFE
            machine_fingerprint: Full fingerprint from MachineFingerprint.generate_fingerprint()
            duration_days:       Override duration (None = use LICENSE_TYPES default)


        Returns:
            (license_key, expiry_date_str)   — expiry_date_str is "YYYYMMDD" or "none"
        """
        type_code    = license_type.upper()[:4]
        machine_hash = machine_fingerprint[:4].upper()

        # Resolve expiry
        ltype    = LICENSE_TYPES.get(type_code, {})
        days     = duration_days if duration_days is not None else ltype.get("duration_days")


        if days is None:
            expiry_str = "none"
        else:
            expiry_str = (datetime.now() + timedelta(days=days)).strftime("%Y%m%d")

        checksum = LicenseKey._make_checksum(type_code, machine_hash, expiry_str)
        key = f"SP-{type_code}-{machine_hash}-{checksum[:4]}-{checksum[4:]}"

        logger.info(f"Generated {type_code} license for machine {machine_hash}, expires {expiry_str}")
        return key, expiry_str

    @staticmethod
    def validate(license_key: str, machine_fingerprint: str) -> Dict[str, Any]:
        """
        Validate a license key against this machine.

        Returns a dict:
          valid          bool
          license_type   str  (e.g. "PREM")
          label          str  (e.g. "Premium")
          expiry_str     str  "YYYYMMDD" or "none"
          days_remaining int or None (None = lifetime)
          error          str or None
        """
        try:
            parts = license_key.strip().upper().split("-")
            # Expected: ['SP', TYPE, MHASH, VAL1, VAL2]
            if len(parts) != 5 or parts[0] != "SP":
                return {"valid": False, "error": "Invalid license key format"}

            _, type_code, machine_hash, val1, val2 = parts

            # 1. Machine binding check
            expected_machine_hash = machine_fingerprint[:4].upper()
            if machine_hash != expected_machine_hash:
                return {"valid": False, "error": "License not valid for this machine"}

            # 2. Type check
            if type_code not in LICENSE_TYPES:
                return {"valid": False, "error": f"Unknown license type: {type_code}"}

            # 3. We need the expiry_str to verify the checksum.
            #    For new-format keys it's embedded via the checksum only,
            #    so we must try candidate expiry values OR read from stored data.
            #    Strategy: read stored license file for expiry_str (set at activation).
            #    This function is also called during activation (no stored file yet),
            #    so we pass expiry_str=None and do a format-only check.
            #    Full expiry check happens in check_license_valid() after reading file.
            #
            #    To keep this function self-contained for activation:
            #    we accept expiry_str as an optional 6th "segment" encoded in the key
            #    by convention.  But since we chose a 5-part key for readability,
            #    we store expiry in the JSON and verify checksum with stored expiry.
            return {
                "valid":        True,
                "license_type": type_code,
                "label":        LICENSE_TYPES[type_code]["label"],
                "checksum_parts": (val1, val2),
                "machine_hash":   machine_hash,
                "error":        None,
            }

        except Exception as e:
            logger.error(f"License validation error: {e}")
            return {"valid": False, "error": f"Validation error: {str(e)}"}

    @staticmethod
    def verify_checksum(license_key: str, expiry_str: str, machine_fingerprint: str) -> bool:
        """
        Full cryptographic checksum verification.
        Call this after reading expiry_str from the stored license file.
        """
        try:
            parts = license_key.strip().upper().split("-")
            if len(parts) != 5:
                return False
            _, type_code, machine_hash, val1, val2 = parts
            expected = LicenseKey._make_checksum(type_code, machine_hash, expiry_str)
            return f"{val1}{val2}" == expected
        except Exception:
            return False


# ============================================================================
# LICENSE MANAGER  (handles activation, storage, expiry)
# ============================================================================

class LicenseManager:
    """
    Manages the full license lifecycle:
      - Generating trial keys
      - Activating customer keys
      - Checking validity on every startup
      - Expiry warnings
    """

    def __init__(self, config_dir: Path):
        self.config_dir  = Path(config_dir)
        self.license_file = self.config_dir / "license.json"


    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------


    def generate_trial(self, machine_fingerprint: str) -> str:
        """Generate and activate a 14-day trial for this machine."""
        key, expiry_str = LicenseKey.generate("TRIA", machine_fingerprint)
        self._store_license(key, "TRIA", expiry_str, user_email=None)
        return key


    def activate(
        self,
        license_key: str,
        machine_fingerprint: str,
        user_email: Optional[str] = None,
        expiry_str: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Activate a license key on this machine.


        For customer keys you've generated offline, you must also supply
        the expiry_str that was produced during generation (you send it
        together with the key, e.g. in a welcome email or encoded in the
        key delivery payload).


        Returns the same dict as LicenseKey.validate().
        """
        result = LicenseKey.validate(license_key, machine_fingerprint)
        if not result["valid"]:
            return result


        # If caller doesn't supply expiry_str, derive it from LICENSE_TYPES
        if expiry_str is None:
            ltype = result["license_type"]
            days  = LICENSE_TYPES.get(ltype, {}).get("duration_days")
            expiry_str = "none" if days is None else (
                datetime.now() + timedelta(days=days)
            ).strftime("%Y%m%d")


        # Cryptographic checksum verification
        if not LicenseKey.verify_checksum(license_key, expiry_str, machine_fingerprint):
            return {"valid": False, "error": "License key checksum failed — key may be tampered"}


        # Check expiry immediately
        expired, days_remaining = self._check_expiry(expiry_str)
        if expired:
            return {"valid": False, "error": "This license key has already expired"}


        self._store_license(license_key, result["license_type"], expiry_str, user_email)


        result["expiry_str"]     = expiry_str
        result["days_remaining"] = days_remaining
        return result


    def check_license_valid(self, machine_fingerprint: str) -> Dict[str, Any]:
        """
        Full startup check — call this from launcher.py.


        Returns:
          valid          bool
          license_type   str
          label          str
          days_remaining int or None
          error          str or None
        """
        stored = self._load_license()
        if not stored:
            return {"valid": False, "error": "No license found"}


        # Structural validation
        result = LicenseKey.validate(stored["license_key"], machine_fingerprint)
        if not result["valid"]:
            return result


        expiry_str = stored.get("expiry_str", "none")


        # Checksum verification (tamper detection)
        if not LicenseKey.verify_checksum(stored["license_key"], expiry_str, machine_fingerprint):
            return {"valid": False, "error": "License file has been tampered with"}


        # Expiry check
        expired, days_remaining = self._check_expiry(expiry_str)
        if expired:
            return {"valid": False, "error": "License has expired — please renew"}


        result["expiry_str"]     = expiry_str
        result["days_remaining"] = days_remaining


        # Expiry warnings
        if days_remaining is not None:
            if days_remaining <= 3:
                logger.warning(f"License expires in {days_remaining} day(s)!")
            elif days_remaining <= 7:
                logger.warning(f"License expires in {days_remaining} days")
            elif days_remaining <= 30:
                logger.info(f"License expires in {days_remaining} days")


        return result


    def get_license_info(self) -> Dict[str, Any]:
        """Return stored license info for display in UI/dashboard."""
        stored = self._load_license()
        if not stored:
            return {"status": "no_license"}
        expiry_str = stored.get("expiry_str", "none")
        _, days_remaining = self._check_expiry(expiry_str)
        return {
            "status":        "active",
            "license_type":  stored.get("license_type"),
            "label":         LICENSE_TYPES.get(stored.get("license_type", ""), {}).get("label", "Unknown"),
            "expiry_str":    expiry_str,
            "days_remaining": days_remaining,
            "user_email":    stored.get("user_email"),
            "activated_at":  stored.get("activated_at"),
        }


    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------


    def _store_license(
        self,
        license_key: str,
        license_type: str,
        expiry_str: str,
        user_email: Optional[str],
    ) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "license_key":  license_key,
            "license_type": license_type,
            "expiry_str":   expiry_str,
            "user_email":   user_email,
            "activated_at": datetime.now().isoformat(),
        }
        with open(self.license_file, "w") as f:
            json.dump(data, f, indent=2)
        try:
            self.license_file.chmod(0o600)
        except Exception:
            pass
        logger.info(f"License stored: {license_type}, expires {expiry_str}")


    def _load_license(self) -> Optional[Dict]:
        if not self.license_file.exists():
            return None
        try:
            with open(self.license_file) as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error reading license file: {e}")
            return None


    @staticmethod
    def _check_expiry(expiry_str: str) -> Tuple[bool, Optional[int]]:
        """Returns (is_expired, days_remaining).  days_remaining=None for lifetime."""
        if expiry_str == "none":
            return False, None
        try:
            expiry = datetime.strptime(expiry_str, "%Y%m%d")
            days   = (expiry - datetime.now()).days
            return days < 0, max(days, 0)
        except Exception:
            return True, 0




# ============================================================================
# UNIFIED AUTHORIZATION MANAGER  (keeps original interface, adds licensing)
# ============================================================================


class AuthorizationManager:
    """
    Main authorization interface.


    Combines machine fingerprinting (was the original "machine" strategy)
    with the new license key + expiry system.  The old STRATEGY class
    variable is retained for backward-compatibility but the recommended
    path for distributed builds is STRATEGY = "license".
    """


    STRATEGY = "license"   # "machine" = dev/internal, "license" = distribution


    def __init__(self, config_dir: Path):
        self.config_dir    = Path(config_dir)
        self.auth_file     = self.config_dir / "authorization.json"
        self.license_mgr   = LicenseManager(config_dir)
        self._fingerprint  = MachineFingerprint.generate_fingerprint()


    # ------------------------------------------------------------------
    # Original interface (kept for backward compatibility with launcher.py)
    # ------------------------------------------------------------------


    def check_authorization(self) -> bool:
        if self.STRATEGY == "machine":
            return self._check_machine_auth()
        elif self.STRATEGY == "license":
            result = self.license_mgr.check_license_valid(self._fingerprint)
            return result["valid"]
        elif self.STRATEGY == "server":
            return self._check_server_auth()
        logger.warning("Unknown auth strategy, allowing access")
        return True


    def register_authorization(self, user_email: Optional[str] = None) -> bool:
        """Register this machine — used during first-time setup."""
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            auth_data = {
                "created":     datetime.now().isoformat(),
                "strategy":    self.STRATEGY,
                "fingerprint": self._fingerprint,
                "hostname":    MachineFingerprint.get_hostname(),
            }
            if user_email:
                auth_data["email"] = user_email
            with open(self.auth_file, "w") as f:
                json.dump(auth_data, f, indent=2)
            try:
                self.auth_file.chmod(0o600)
            except Exception:
                pass
            logger.info("Machine authorization registered")
            return True
        except Exception as e:
            logger.error(f"Authorization registration error: {e}")
            return False


    def get_authorization_info(self) -> Dict[str, Any]:
        if not self.auth_file.exists():
            return {"status": "not_registered"}
        try:
            with open(self.auth_file) as f:
                info = json.load(f)
            info["license"] = self.license_mgr.get_license_info()
            return info
        except Exception as e:
            return {"status": "error", "message": str(e)}


    def get_machine_id(self) -> str:
        """Short 4-char machine ID used in license keys."""
        return MachineFingerprint.get_machine_id()


    # ------------------------------------------------------------------
    # Internal helpers (original machine strategy kept intact)
    # ------------------------------------------------------------------


    def _check_machine_auth(self) -> bool:
        if not self.auth_file.exists():
            logger.warning("No authorization file — first-time setup")
            return True
        try:
            with open(self.auth_file) as f:
                auth_data = json.load(f)
            stored_fp = auth_data.get("fingerprint")
            if not stored_fp:
                logger.error("No fingerprint in auth file")
                return False
            return MachineFingerprint.verify_fingerprint(stored_fp)
        except Exception as e:
            logger.error(f"Machine auth error: {e}")
            return False


    def _check_server_auth(self) -> bool:
        """Placeholder — implement with your server endpoint when ready."""
        logger.warning("Server auth not yet implemented, allowing access")
        return True




# ============================================================================
# SERVER-BASED VALIDATION  (future — unchanged from original)
# ============================================================================


class ServerAuth:
    AUTH_SERVER = "https://auth.sp-trading.app"


    @staticmethod
    def validate_user(username: str, token: str) -> bool:
        try:
            import requests
            response = requests.post(
                f"{ServerAuth.AUTH_SERVER}/validate",
                json={"username": username, "token": token},
                timeout=5,
            )
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Server validation error: {e}")
            return True   # fail-open for offline use




# ============================================================================
# LAUNCHER INTEGRATION  (same function signatures as before)
# ============================================================================


def check_authorization_before_launch(config_dir: Path) -> bool:
    """
    Called from launcher.py before starting the main app.
    Returns True if authorized, False if access should be denied.
    """
    auth = AuthorizationManager(config_dir)
    return auth.check_authorization()




def register_machine(config_dir: Path, user_email: Optional[str] = None) -> bool:
    """Called from launcher.py setup wizard."""
    auth = AuthorizationManager(config_dir)
    print(f"{NOTE} Registering this machine for S-P Trading...")
    if auth.register_authorization(user_email):
        print(f"{CHECK} Machine registration successful!")
        return True
    print(f"{CROSS} Registration failed")
    return False




# ============================================================================
# KEY GENERATOR UTILITY  (run this on YOUR machine to generate customer keys)
# ============================================================================


def generate_customer_key(
    license_type: str,
    customer_machine_id_4char: str,
    duration_days: Optional[int] = None,
    user_email: Optional[str] = None,
) -> None:
    """
    Run this utility on YOUR developer machine to generate keys for customers.


    The customer sends you their Machine ID (4-char) which they can find by
    running:  python authorization.py --machine-id


    Usage example:
        python authorization.py --generate PREM A7F2 --email user@email.com
    """
    # We need a full 64-char fingerprint for the HMAC; pad the 4-char ID.
    # Use a deterministic expansion so the checksum is reproducible.
    padded_fp = customer_machine_id_4char.upper().ljust(64, "0")


    key, expiry_str = LicenseKey.generate(license_type, padded_fp, duration_days)


    print("\n" + "=" * 60)
    print(f"  LICENSE KEY GENERATED")
    print("=" * 60)
    print(f"  Customer Machine ID : {customer_machine_id_4char.upper()}")
    print(f"  License Type        : {LICENSE_TYPES.get(license_type.upper()[:4], {}).get('label', license_type)}")
    print(f"  License Key         : {key}")
    print(f"  Expires             : {'Never' if expiry_str == 'none' else expiry_str}")
    if user_email:
        print(f"  Email               : {user_email}")
    print("=" * 60)
    print("\nSend the customer:")
    print(f"  Key    : {key}")
    print(f"  Expiry : {expiry_str}")
    print("\n(The customer needs BOTH the key AND the expiry string for activation.)\n")




# ============================================================================
# CLI  (python authorization.py --machine-id  /  --generate  /  --info)
# ============================================================================


if __name__ == "__main__":
    import sys
    import argparse


    parser = argparse.ArgumentParser(description="S-P Trading License Utility")
    parser.add_argument("--machine-id",  action="store_true", help="Print this machine's ID (send to developer to get a key)")
    parser.add_argument("--info",        action="store_true", help="Show current license info")
    parser.add_argument("--generate",    nargs=2, metavar=("TYPE", "MACHINE_ID_4CHAR"),
                        help="Generate a key: --generate PREM A7F2")
    parser.add_argument("--email",       default=None, help="Customer email (optional, used with --generate)")
    parser.add_argument("--days",        type=int, default=None, help="Override duration days")
    parser.add_argument("--activate",    nargs=2, metavar=("KEY", "EXPIRY"),
                        help="Activate a key on this machine: --activate SP-PREM-... 20270101")
    parser.add_argument("--trial",       action="store_true", help="Start a 14-day trial on this machine")


    args = parser.parse_args()


    config_dir = Path.home() / ".sp-trading"
    config_dir.mkdir(exist_ok=True)


    fp = MachineFingerprint.generate_fingerprint()


    if args.machine_id:
        mid = MachineFingerprint.get_machine_id()
        print(f"\nYour Machine ID: {mid}")
        print("Send this to the developer to receive your license key.\n")


    elif args.info:
        mgr = LicenseManager(config_dir)
        info = mgr.get_license_info()
        print(json.dumps(info, indent=2))


    elif args.generate:
        license_type, machine_id_4char = args.generate
        generate_customer_key(license_type, machine_id_4char, args.days, args.email)


    elif args.activate:
        key, expiry_str = args.activate
        mgr    = LicenseManager(config_dir)
        result = mgr.activate(key, fp, expiry_str=expiry_str)
        if result["valid"]:
            print(f"\n{CHECK} License activated!")
            print(f"  Type    : {result.get('label')}")
            print(f"  Expires : {'Never' if expiry_str == 'none' else expiry_str}")
            if result.get("days_remaining") is not None:
                print(f"  Days    : {result['days_remaining']} remaining")
        else:
            print(f"\n{CROSS} Activation failed: {result['error']}")


    elif args.trial:
        mgr = LicenseManager(config_dir)
        key = mgr.generate_trial(fp)
        print(f"\n{CHECK} 14-day trial activated!")
        print(f"  Key: {key}\n")


    else:
        parser.print_help()
