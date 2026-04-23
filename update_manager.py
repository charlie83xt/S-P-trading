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
from typing import Dict, List, Optional, Tuple


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
        """Fallback version comparison (works for semver X.Y.Z)."""
        def _parts(v):
            return tuple(int(x) for x in v.lstrip("v").split("."))
        try:
            return _parts(latest) > _parts(current)
        except Exception:
            return False


from version import APP_VERSION

logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURATION  — change these before distribution
# ============================================================================

# GitHub public repo example:
#   "https://api.github.com/repos/YOUR_GITHUB_USERNAME/sp-trading/releases/latest"
# Private server example:
#   "https://updates.your-domain.com/api/latest"
UPDATE_CHECK_URL = "https://api.github.com/repos/YOUR_GITHUB_USERNAME/sp-trading/releases/latest"

# Seconds to wait for network requests
REQUEST_TIMEOUT = 10


# How many backup snapshots to keep before pruning old ones
MAX_BACKUPS = 5


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
        Returns an update-info dict if a newer version is available, or
        None if we are up to date / the check fails.

        Update-info dict:
            version          str   "1.2.0"
            release_date     str   "2026-04-23"
            changelog        str   release notes
            files            list  [{filename, sha256, description}, ...]
            download_base_url str
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
                "version":          latest_version,
                "release_date":     data.get("published_at", "")[:10],
                "changelog":        data.get("body", ""),
                "files":            manifest.get("files", []),
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
        Returns True if all files downloaded and verified successfully.
        """
        base_url      = update_info.get("download_base_url", "")
        files_to_get  = update_info.get("files", [])

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
                        logger.error(f"    Hash mismatch — expected {expected_hash[:12]}… got {actual[:12]}…")
                        return False

                logger.info(f"    ✓ verified")

            except Exception as e:
                logger.error(f"    Error downloading {filename}: {e}")
                return False

        logger.info("All update files downloaded and verified.")
        return True

    # ------------------------------------------------------------------
    # 3. BACKUP
    # ------------------------------------------------------------------

    def backup_current_files(self, files_to_update: List[Dict]) -> Optional[str]:
        """
        Snapshot the current versions of files about to be updated.


        Returns the backup directory name (used for rollback) or None on failure.
        """
        timestamp   = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = self.backup_dir / f"backup_{timestamp}"
        backup_path.mkdir(parents=True, exist_ok=True)


        logger.info(f"Creating backup snapshot: {backup_path.name}")


        for file_info in files_to_update:
            filename = file_info["filename"]
            src      = self.app_dir / filename
            if src.exists():
                dst = backup_path / filename
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                logger.debug(f"  Backed up {filename}")


        self._prune_old_backups()
        return backup_path.name

    # ------------------------------------------------------------------
    # 4. APPLY
    # ------------------------------------------------------------------

    def apply_updates(self, files_to_update: List[Dict]) -> bool:
        """
        Copy staged files from .updates/ into the app directory.
        """
        logger.info("Applying updates...")


        for file_info in files_to_update:
            filename = file_info["filename"]
            src      = self.update_dir / filename
            dst      = self.app_dir / filename


            if not src.exists():
                logger.error(f"Staged file missing: {filename}")
                return False


            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            logger.info(f"  ✓ {filename}")


        logger.info("Updates applied successfully.")
        return True


    # ------------------------------------------------------------------
    # 5. ROLLBACK
    # ------------------------------------------------------------------

    def rollback(self, backup_dir_name: str) -> bool:
        """
        Restore files from a named backup snapshot.
        """
        backup_path = self.backup_dir / backup_dir_name
        if not backup_path.exists():
            logger.error(f"Backup not found: {backup_path}")
            return False


        logger.info(f"Rolling back from: {backup_dir_name}")
        for src in backup_path.rglob("*"):
            if src.is_file():
                rel = src.relative_to(backup_path)
                dst = self.app_dir / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                logger.info(f"  Restored {rel}")


        logger.info("Rollback complete.")
        return True

    # ------------------------------------------------------------------
    # 6. FULL UPDATE FLOW
    # ------------------------------------------------------------------

    def perform_update(self, update_info: Dict, auto_apply: bool = False) -> bool:
        """
        Orchestrate the full check → download → backup → apply cycle.

        If auto_apply is False, prompts the user for confirmation first.
        Returns True if the update was applied successfully.
        """
        version  = update_info["version"]
        files    = update_info["files"]
        changelog = update_info.get("changelog", "").strip()


        print(f"\n{'='*60}")
        print(f"  UPDATE AVAILABLE: v{version}")
        print(f"{'='*60}")
        if changelog:
            # Show first 500 chars of release notes
            notes = changelog[:500] + ("…" if len(changelog) > 500 else "")
            print(f"\nWhat's new:\n{notes}\n")
        print(f"Files to update: {len(files)}")
        for f in files:
            print(f"  • {f['filename']}")


        if not auto_apply:
            answer = input("\nInstall update now? (yes/no): ").strip().lower()
            if answer not in ("yes", "y"):
                logger.info("User declined update")
                return False


        # Download
        if not self.download_update_files(update_info):
            logger.error("Download failed — update aborted")
            return False


        # Backup
        backup_name = self.backup_current_files(files)
        if backup_name is None:
            logger.error("Backup failed — update aborted")
            return False


        # Apply
        if not self.apply_updates(files):
            logger.error("Apply failed — attempting rollback")
            self.rollback(backup_name)
            return False


        logger.info(f"Successfully updated to v{version}")
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
# MANIFEST GENERATOR  (run on your dev machine before each release)
# ============================================================================

def create_update_manifest(
    version: str,
    files: List[str],
    github_username: str,
    repo_name: str = "sp-trading",
) -> None:
    """
    Generate update_manifest.json to upload alongside a GitHub release.


    Args:
        version:         Release version string e.g. "1.2.0"
        files:           List of relative file paths to include in the update
        github_username: Your GitHub username
        repo_name:       Your GitHub repository name
    """
    base_url = f"https://github.com/{github_username}/{repo_name}/releases/download/v{version}"
    manifest = {
        "version":          version,
        "release_date":     datetime.now().strftime("%Y-%m-%d"),
        "download_base_url": base_url,
        "files": [],
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
    print(f"Upload this file (and all listed .py / .json / .html files) to the v{version} GitHub release.")


# ============================================================================
# LAUNCHER INTEGRATION  (call this from launcher.py at startup)
# ============================================================================

def check_and_apply_updates(
    app_dir: Path,
    auto_update: bool = False,
    background: bool = True,
) -> None:
    """
    Entry point called from launcher.py.


    Runs the update check in a background thread by default so it never
    blocks or slows down the app startup.  Set background=False in tests.


    Args:
        app_dir:      Root directory of the running app (Path.cwd() or sys._MEIPASS parent)
        auto_update:  If True, apply silently without prompting the user
        background:   If True, run in a daemon thread (default)
    """
    def _run():
        try:
            updater     = UpdateManager(app_dir)
            update_info = updater.check_for_updates()


            if update_info:
                applied = updater.perform_update(update_info, auto_apply=auto_update)
                if applied:
                    print("\n🔄 Update applied — please restart the app to use the new version.\n")
            else:
                logger.debug("No updates available")


        except Exception as e:
            logger.error(f"Update check/apply error: {e}")
            # Never crash the app because of a failed update


    if background:
        t = threading.Thread(target=_run, daemon=True, name="update-checker")
        t.start()
    else:
        _run()


# ============================================================================
# CLI  (python update_manager.py --check / --manifest / --rollback)
# ============================================================================

if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

    parser = argparse.ArgumentParser(description="S-P Trading Update Manager")
    sub    = parser.add_subparsers(dest="cmd")

    # check
    p_check = sub.add_parser("check", help="Check for and optionally apply updates")
    p_check.add_argument("--auto",  action="store_true", help="Apply without prompting")

    # manifest  (developer use)
    p_mf = sub.add_parser("manifest", help="Generate update_manifest.json for a release")
    p_mf.add_argument("version",  help="Version string e.g. 1.2.0")
    p_mf.add_argument("files",    nargs="+", help="Files to include in the update")
    p_mf.add_argument("--user",   required=True, help="GitHub username")
    p_mf.add_argument("--repo",   default="sp-trading", help="GitHub repo name")

    # rollback
    p_rb = sub.add_parser("rollback", help="Roll back to a backup snapshot")
    p_rb.add_argument("backup_name", help="Backup directory name e.g. backup_20260423_120000")


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
