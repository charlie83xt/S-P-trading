"""
FIRST-RUN DETECTION & SETUP ROUTES for S-P Trading


This module provides:
  1. is_first_run()        — called from launcher.py to decide the startup URL
  2. register_setup_routes(app) — Flask Blueprint with all /setup and /api/setup/* endpoints
  3. complete_first_run()  — marks setup as done (deletes the first_run marker file)


HOW TO INTEGRATE
────────────────
In web_app.py, add near the top imports:


    from first_run import register_setup_routes
    register_setup_routes(app)


In launcher.py, change the browser-open section:


    from first_run import is_first_run
    ...
    startup_url = f"http://localhost:{dashboard_port}/setup" if is_first_run() else dashboard_url
    webbrowser.open(startup_url)
"""


import os
import json
import logging
from pathlib import Path
from typing import Optional


from flask import Blueprint, render_template, request, jsonify, redirect, url_for


from app_config import get_app_config_dir, load_env_file, save_env_file
from authorization import (
    MachineFingerprint,
    LicenseManager,
    AuthorizationManager,
)


logger = logging.getLogger(__name__)


# ── Locate the per-user app data directory ───────────────────────────────────
_config_dir: Optional[Path] = None


def _get_config_dir() -> Path:
    global _config_dir
    if _config_dir is None:
        _config_dir = get_app_config_dir()
    return _config_dir




# ============================================================================
# FIRST-RUN DETECTION
# ============================================================================


def is_first_run() -> bool:
    """
    Returns True if this is the first time the app has been launched
    on this machine (i.e. the user has not completed setup yet).


    Called from launcher.py to pick the right startup URL.
    """
    config_dir = _get_config_dir()


    # Installer writes a 'first_run' marker; setup completion deletes it.
    first_run_marker = config_dir / "first_run"
    license_file     = config_dir / "license.json"


    # It's a first run if either:
    #   • the installer's 'first_run' marker exists, OR
    #   • there is no license.json yet (fresh install without the installer)
    return first_run_marker.exists() or not license_file.exists()




def complete_first_run() -> None:
    """Mark setup as done by removing the first_run marker."""
    marker = _get_config_dir() / "first_run"
    try:
        if marker.exists():
            marker.unlink()
            logger.info("First-run marker removed — setup complete")
    except Exception as e:
        logger.warning(f"Could not remove first_run marker: {e}")




# ============================================================================
# FLASK BLUEPRINT
# ============================================================================


setup_bp = Blueprint("setup", __name__)




# ── Setup page (GET /setup) ───────────────────────────────────────────────────
@setup_bp.route("/setup")
def setup_page():
    """
    Serve the first-run setup UI.
    If setup is already done, redirect to the main dashboard.
    """
    if not is_first_run():
        return redirect(url_for("index"))          # adjust "index" to your main route name
    return render_template("setup.html")




# ── Machine ID ────────────────────────────────────────────────────────────────
@setup_bp.route("/api/setup/machine_id")
def api_machine_id():
    mid = MachineFingerprint.get_machine_id()
    return jsonify({"machine_id": mid})




# ── Trial activation ──────────────────────────────────────────────────────────
@setup_bp.route("/api/setup/trial", methods=["POST"])
def api_trial():
    try:
        config_dir  = _get_config_dir()
        fingerprint = MachineFingerprint.generate_fingerprint()
        lic_mgr     = LicenseManager(config_dir)


        # Don't allow generating a second trial if one already exists
        existing = lic_mgr.check_license_valid(fingerprint)
        if existing["valid"]:
            return jsonify({
                "success": True,
                "label":      existing.get("label", ""),
                "expires":    existing.get("expiry_str", "none"),
                "machine_id": fingerprint[:4].upper(),
            })


        key = lic_mgr.generate_trial(fingerprint)
        info = lic_mgr.get_license_info()


        return jsonify({
            "success":    True,
            "label":      info.get("label", "Trial"),
            "expires":    info.get("expiry_str", ""),
            "machine_id": fingerprint[:4].upper(),
        })


    except Exception as e:
        logger.error(f"Trial activation error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500




# ── License key activation ────────────────────────────────────────────────────
@setup_bp.route("/api/setup/activate", methods=["POST"])
def api_activate():
    try:
        data        = request.get_json() or {}
        license_key = data.get("license_key", "").strip()
        expiry_str  = data.get("expiry_str", "").strip() or None
        user_email  = data.get("user_email", "").strip() or None


        if not license_key:
            return jsonify({"success": False, "error": "License key is required"}), 400


        config_dir  = _get_config_dir()
        fingerprint = MachineFingerprint.generate_fingerprint()
        lic_mgr     = LicenseManager(config_dir)


        result = lic_mgr.activate(
            license_key,
            fingerprint,
            user_email=user_email,
            expiry_str=expiry_str,
        )


        if result["valid"]:
            info = lic_mgr.get_license_info()
            return jsonify({
                "success":    True,
                "label":      result.get("label", ""),
                "expires":    info.get("expiry_str", "none"),
                "machine_id": fingerprint[:4].upper(),
            })
        else:
            return jsonify({"success": False, "error": result.get("error", "Invalid license")}), 400


    except Exception as e:
        logger.error(f"License activation error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500




# ── Tradovate credentials ─────────────────────────────────────────────────────
@setup_bp.route("/api/setup/credentials", methods=["POST"])
def api_credentials():
    try:
        data     = request.get_json() or {}
        username = data.get("username", "").strip()
        password = data.get("password", "")


        if not username or not password:
            return jsonify({"success": False, "error": "Username and password are required"}), 400


        env_vars = load_env_file()
        env_vars["TRADOVATE_USERNAME"] = username
        env_vars["TRADOVATE_PASSWORD"] = password
        save_env_file(env_vars)


        # Also update os.environ so the running app picks them up immediately
        os.environ["TRADOVATE_USERNAME"] = username
        os.environ["TRADOVATE_PASSWORD"] = password


        logger.info("Tradovate credentials saved successfully")
        return jsonify({"success": True})


    except Exception as e:
        logger.error(f"Credentials save error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500




# ── Complete setup ─────────────────────────────────────────────────────────────
@setup_bp.route("/api/setup/complete", methods=["POST"])
def api_complete():
    try:
        config_dir  = _get_config_dir()


        # Process any pending license from installer
        _process_pending_installer_license(config_dir)


        # Remove first-run marker
        complete_first_run()


        logger.info("First-run setup completed successfully")
        return jsonify({"success": True})


    except Exception as e:
        logger.error(f"Setup completion error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500




# ── Register blueprint with the Flask app ─────────────────────────────────────
def register_setup_routes(app):
    """
    Call this from web_app.py after creating the Flask app:


        from first_run import register_setup_routes
        register_setup_routes(app)
    """
    app.register_blueprint(setup_bp)
    logger.info("Setup routes registered (/setup, /api/setup/*)")




# ============================================================================
# INSTALLER PENDING LICENSE  (written by Inno Setup wizard)
# ============================================================================


def _process_pending_installer_license(config_dir: Path) -> None:
    """
    If the Inno Setup wizard captured a license key, it wrote it to
    pending_license.json.  Pick that up and activate it now.
    """
    pending_file = config_dir / "pending_license.json"
    if not pending_file.exists():
        return


    try:
        with open(pending_file) as f:
            pending = json.load(f)


        license_key = pending.get("license_key", "").strip()
        expiry_str  = pending.get("expiry_str", "").strip() or None
        user_email  = pending.get("user_email", "").strip() or None


        if license_key:
            fingerprint = MachineFingerprint.generate_fingerprint()
            lic_mgr     = LicenseManager(config_dir)
            result      = lic_mgr.activate(
                license_key,
                fingerprint,
                user_email=user_email,
                expiry_str=expiry_str,
            )
            if result["valid"]:
                logger.info("Installer-provided license activated successfully")
            else:
                logger.warning(f"Installer license activation failed: {result.get('error')}")


        # Remove the pending file regardless
        pending_file.unlink()


    except Exception as e:
        logger.error(f"Error processing installer license: {e}")
