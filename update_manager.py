"""
AUTO-UPDATE SYSTEM for S-P Trading App.

Downloads and applies file-level updates (strategies, configs, selectors,
templates) without requiring a full .exe rebuild or reinstall.

Architecture:
    GitHub Releases (or private server)
         ↓
    Version check → compare against APP_VERSION
         ↓
    Download update_manifest.json
         ↓
    Download changed files to .updates/ staging area
         ↓
    Backup current files to .backups/{timestamp}/
         ↓
    Apply updates (overwrite target files)
         ↓
    App restart (if needed)

What CAN be updated without repackaging:
    ✅  Python strategy files  (_internal/*.py in the dist folder)
    ✅  Config / selector JSON files
    ✅  Flask templates (templates/*.html)
    ❌  The .exe itself  (requires full Inno Setup installer)

Usage from launcher.py:
    from update_manager import check_and_apply_updates
    check_and_apply_updates(app_dir=Path.cwd(), logger=logger)
"""

import sys
import os
import json
import shutil
import hashlib
import logging
import threading
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional


try:
    import requests
    _REQUESTS_AVAILABLE = True
except ImportError:
    _REQUESTS_AVAILABLE = False


try:
    from packaging.version import Version as PkgVersion
    def _newer(latest: str, current: str) -> bool:
        return PkgVersion(latest) > PkgVersion(current)
except ImportError:
    def _newer(latest: str, current: str) -> bool:
        def _parts(v):
            return tuple(int(x) for x in v.lstrip("v").split("."))
        try:
            return _parts(latest) > _parts(current)
        except Exception:
            return False


from version import APP_VERSION

logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURATION
# ============================================================================

UPDATE_CHECK_URL = "https://api.github.com/repos/charlie83xt/S-P-trading/releases/latest"
REQUEST_TIMEOUT  = 10
MAX_BACKUPS      = 5


# ============================================================================
# PATH HELPERS  ← THE CORE FIX
# ============================================================================

def _get_internal_dir(app_dir: Path) -> Path:
    """
    Return the directory where .py and .json files actually live.

    Packaged app layout:
        S-P Trading/              ← app_dir
        S-P Trading/_internal/    ← where Python files live  ← CORRECT TARGET
        S-P Trading/templates/    ← where HTML templates live

    Development layout:
        project_root/             ← app_dir (no _internal subfolder)
    """
    internal = app_dir / "_internal"
    if internal.is_dir():
        return internal
    return app_dir  # dev mode: files are in project root directly


def _resolve_dst(app_dir: Path, filename: str) -> Path:
    """
    Map a filename from the update manifest to its correct destination path.

    Rules (in order):
      templates/*  → app_dir/templates/filename  (Flask HTML files)
      *.py         → _internal/basename           (Python modules)
      *.json       → _internal/basename           (JSON config/selectors)
      anything else → app_dir/filename            (unknown, best guess)
    """
    p = Path(filename)

    # Templates: preserve the templates/ subfolder under app_dir
    if p.parts and p.parts[0] == "templates":
        return app_dir / p

    # Python and JSON: go into _internal on packaged apps
    if p.suffix in (".py", ".json"):
        return _get_internal_dir(app_dir) / p.name

    # Fallback
    return app_dir / p


# ============================================================================
# UPDATE MANAGER
# ============================================================================

class UpdateManager:
    """
    Manages the full update lifecycle: check → download → backup → apply.
    """

    def __init__(self, app_dir: Path):
        self.app_dir    = Path(app_dir)
        self.update_dir = self.app_dir / ".updates"
        self.backup_dir = self.app_dir / ".backups"
        self.update_dir.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # 1. VERSION CHECK
    # ------------------------------------------------------------------

    def check_for_updates(self) -> Optional[Dict]:
        """
        Query the update server for the latest release.
        Returns an update-info dict if a newer version is available,
        or None if up to date / check fails.
        """
        if not _REQUESTS_AVAILABLE:
            logger.warning("requests library not installed — skipping update check")
            return None

        try:
            logger.info(f"Checking for updates (current: v{APP_VERSION})...")
            resp = requests.get(
                UPDATE_CHECK_URL,
                timeout=REQUEST_TIMEOUT,
                headers={"Accept": "application/json"},
            )
            if resp.status_code != 200:
                logger.warning(f"Update server returned HTTP {resp.status_code}")
                return None

            data           = resp.json()
            latest_version = data.get("tag_name", "").lstrip("v")

            if not latest_version:
                logger.warning("Could not parse version from update server response")
                return None

            if not _newer(latest_version, APP_VERSION):
                logger.info(f"App is up to date (v{APP_VERSION})")
                return None

            logger.info(f"Update available: v{latest_version}")

            # Find update_manifest.json in the release assets
            manifest_url = None
            for asset in data.get("assets", []):
                if asset.get("name") == "update_manifest.json":
                    manifest_url = asset["browser_download_url"]
                    break

            if not manifest_url:
                logger.warning("No update_manifest.json found in release assets")
                return None

            manifest_resp = requests.get(manifest_url, timeout=REQUEST_TIMEOUT)
            if manifest_resp.status_code != 200:
                logger.warning("Could not download update manifest")
                return None

            manifest = manifest_resp.json()
            return {
                "version":           latest_version,
                "release_date":      data.get("published_at", "")[:10],
                "changelog":         data.get("body", ""),
                "files":             manifest.get("files", []),
                "download_base_url": manifest.get("download_base_url", ""),
            }

        except Exception as e:
            logger.error(f"Update check failed: {e}")
            return None

    # ------------------------------------------------------------------
    # 2. DOWNLOAD
    # ------------------------------------------------------------------

    def download_update_files(self, update_info: Dict) -> bool:
        """
        Download changed files to the .updates/ staging directory.
        Each file is hash-verified after download.
        """
        base_url     = update_info.get("download_base_url", "")
        files_to_get = update_info.get("files", [])

        if not files_to_get:
            logger.warning("Update manifest contains no files")
            return False

        logger.info(f"Downloading {len(files_to_get)} update file(s)...")

        for file_info in files_to_get:
            filename      = file_info["filename"]
            expected_hash = file_info.get("sha256")
            url           = f"{base_url}/{filename}"

            logger.info(f"  → {filename}")
            try:
                resp = requests.get(url, timeout=30)
                if resp.status_code != 200:
                    logger.error(f"    Failed (HTTP {resp.status_code})")
                    return False

                dest = self.update_dir / filename
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(resp.content)

                if expected_hash:
                    actual = self._sha256(dest)
                    if actual != expected_hash:
                        logger.error(
                            f"    Hash mismatch — expected {expected_hash[:12]}… "
                            f"got {actual[:12]}…"
                        )
                        return False

                logger.info(f"    ✓ verified")

            except Exception as e:
                logger.error(f"    Error downloading {filename}: {e}")
                return False

        logger.info("All update files downloaded and verified.")
        return True

    # ------------------------------------------------------------------
    # 3. BACKUP  — reads from correct _internal location
    # ------------------------------------------------------------------

    def backup_current_files(self, files_to_update: List[Dict]) -> Optional[str]:
        """
        Snapshot the current versions of files about to be updated.
        Reads from the correct location (_internal for .py/.json files).
        """
        timestamp   = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = self.backup_dir / f"backup_{timestamp}"
        backup_path.mkdir(parents=True, exist_ok=True)

        logger.info(f"Creating backup snapshot: {backup_path.name}")

        for file_info in files_to_update:
            filename = file_info["filename"]
            src      = _resolve_dst(self.app_dir, filename)  # same logic as apply

            if src.exists():
                dst = backup_path / filename
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                logger.debug(f"  Backed up {filename} ← {src}")
            else:
                logger.debug(f"  Skipped backup for {filename} (not found at {src})")

        self._prune_old_backups()
        return backup_path.name

    # ------------------------------------------------------------------
    # 4. APPLY  — writes to correct _internal location
    # ------------------------------------------------------------------

    def apply_updates(self, files_to_update: List[Dict]) -> bool:
        """
        Copy staged files from .updates/ into the correct app directories.

        Key routing (packaged app):
          *.py / *.json  →  S-P Trading/_internal/filename
          templates/*    →  S-P Trading/templates/filename
        """
        logger.info("Applying updates...")
        logger.info(f"  app_dir   = {self.app_dir}")
        logger.info(f"  _internal = {_get_internal_dir(self.app_dir)}")

        for file_info in files_to_update:
            filename = file_info["filename"]
            src      = self.update_dir / filename

            if not src.exists():
                logger.error(f"Staged file missing: {filename} (looked in {src})")
                return False

            dst = _resolve_dst(self.app_dir, filename)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            logger.info(f"  ✓ {filename} → {dst}")

        logger.info("Updates applied successfully.")
        return True

    # ------------------------------------------------------------------
    # 5. ROLLBACK
    # ------------------------------------------------------------------

    def rollback(self, backup_dir_name: str) -> bool:
        """Restore files from a named backup snapshot."""
        backup_path = self.backup_dir / backup_dir_name
        if not backup_path.exists():
            logger.error(f"Backup not found: {backup_path}")
            return False

        logger.info(f"Rolling back from: {backup_dir_name}")
        for src in backup_path.rglob("*"):
            if src.is_file():
                rel = src.relative_to(backup_path)
                dst = _resolve_dst(self.app_dir, str(rel))
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                logger.info(f"  Restored {rel} → {dst}")

        logger.info("Rollback complete.")
        return True

    # ------------------------------------------------------------------
    # 6. FULL UPDATE FLOW
    # ------------------------------------------------------------------

    def perform_update(self, update_info: Dict, auto_apply: bool = False) -> bool:
        """
        Orchestrate the full check → download → backup → apply cycle.

        If auto_apply is False:
          Writes pending_update.json for the dashboard banner — NO input() call.

        Returns True if update was applied, False otherwise.
        """
        version   = update_info["version"]
        files     = update_info["files"]
        changelog = update_info.get("changelog", "").strip()

        if not auto_apply:
            # Write pending_update.json — dashboard banner picks this up
            pending_file = self.update_dir / "pending_update.json"
            pending_file.parent.mkdir(parents=True, exist_ok=True)
            pending_file.write_text(json.dumps({
                "version":           version,
                "changelog":         changelog,
                "files":             files,
                "download_base_url": update_info.get("download_base_url", ""),
            }, indent=2))
            logger.info(
                f"Update v{version} available — "
                f"pending_update.json written for dashboard banner"
            )
            return False  # Waiting for user confirmation via dashboard

        # ── auto_apply=True: full download → backup → apply ──
        if not self.download_update_files(update_info):
            logger.error("Download failed — update aborted")
            return False

        backup_name = self.backup_current_files(files)
        if backup_name is None:
            logger.error("Backup failed — update aborted")
            return False

        if not self.apply_updates(files):
            logger.error("Apply failed — attempting rollback")
            self.rollback(backup_name)
            return False

        logger.info(f"Successfully updated to v{version}")

        # Clean up pending file
        pending_file = self.update_dir / "pending_update.json"
        if pending_file.exists():
            pending_file.unlink()

        return True

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _sha256(path: Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    def _prune_old_backups(self):
        backups = sorted(self.backup_dir.glob("backup_*"), reverse=True)
        for old in backups[MAX_BACKUPS:]:
            try:
                shutil.rmtree(old)
                logger.debug(f"Pruned old backup: {old.name}")
            except Exception:
                pass


# ============================================================================
# MANIFEST GENERATOR  (run on your dev Mac before each release)
# ============================================================================

def create_update_manifest(
    version: str,
    files: List[str],
    github_username: str,
    repo_name: str = "S-P-trading",
) -> None:
    """
    Generate update_manifest.json to upload alongside a GitHub release.
    """
    base_url = (
        f"https://github.com/{github_username}/{repo_name}"
        f"/releases/download/v{version}"
    )
    manifest = {
        "version":           version,
        "release_date":      datetime.now().strftime("%Y-%m-%d"),
        "download_base_url": base_url,
        "files":             [],
    }

    for filename in files:
        p = Path(filename)
        if not p.exists():
            print(f"  WARNING: {filename} not found — skipping")
            continue
        h = hashlib.sha256(p.read_bytes()).hexdigest()
        manifest["files"].append({
            "filename":    filename,
            "sha256":      h,
            "description": "",
        })
        print(f"  ✓ {filename}  ({h[:12]}…)")

    out = Path("update_manifest.json")
    out.write_text(json.dumps(manifest, indent=2))
    print(f"\nManifest written to {out.resolve()}")
    print(
        f"Upload update_manifest.json AND all listed files "
        f"to the v{version} GitHub release assets."
    )


# ============================================================================
# LAUNCHER INTEGRATION
# ============================================================================

def check_and_apply_updates(
    app_dir: Path,
    auto_update: bool = False,
    background: bool = True,
) -> None:
    """
    Entry point called from launcher.py on startup.
    Runs in a background thread — never blocks startup.
    """
    def _run():
        try:
            updater     = UpdateManager(app_dir)
            update_info = updater.check_for_updates()

            if update_info:
                applied = updater.perform_update(update_info, auto_apply=auto_update)
                if applied:
                    logger.info(
                        f"Update applied to v{update_info['version']} "
                        f"— restart the app to use the new version"
                    )
            else:
                logger.debug("No updates available")

        except Exception as e:
            logger.error(f"Update check/apply error: {e}")

    if background:
        t = threading.Thread(target=_run, daemon=True, name="update-checker")
        t.start()
    else:
        _run()


# ============================================================================
# CLI
# ============================================================================

if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

    parser = argparse.ArgumentParser(description="S-P Trading Update Manager")
    sub    = parser.add_subparsers(dest="cmd")

    p_check = sub.add_parser("check", help="Check for and optionally apply updates")
    p_check.add_argument("--auto", action="store_true", help="Apply without prompting")

    p_mf = sub.add_parser("manifest", help="Generate update_manifest.json for a release")
    p_mf.add_argument("version", help="Version string e.g. 1.2.0")
    p_mf.add_argument("files",   nargs="+", help="Files to include in the update")
    p_mf.add_argument("--user",  required=True, help="GitHub username")
    p_mf.add_argument("--repo",  default="S-P-trading", help="GitHub repo name")

    p_rb = sub.add_parser("rollback", help="Roll back to a backup snapshot")
    p_rb.add_argument("backup_name", help="e.g. backup_20260423_120000")

    args = parser.parse_args()

    if args.cmd == "check":
        check_and_apply_updates(Path.cwd(), auto_update=args.auto, background=False)
    elif args.cmd == "manifest":
        print(f"\nGenerating manifest for v{args.version}:")
        create_update_manifest(args.version, args.files, args.user, args.repo)
    elif args.cmd == "rollback":
        um = UpdateManager(Path.cwd())
        ok = um.rollback(args.backup_name)
        sys.exit(0 if ok else 1)
    else:
        parser.print_help()


