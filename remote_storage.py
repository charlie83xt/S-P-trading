"""
remote_storage.py — backend-agnostic remote storage via rclone.

A configured rclone remote (Google Drive, S3, GCS, B2, ...) is the source of
truth. Code reads a LOCAL cache; sync moves data between cache and remote.
Switching provider = change one remote name in config, no code change.

Needs the `rclone` binary on PATH (single static binary — bundle it with the
packaged app or install via package manager). If rclone/remote are absent,
every call degrades to local-only and logs a warning, so the bot never breaks
offline.
"""
from __future__ import annotations
import os, shutil, subprocess, logging
from typing import Optional

logger = logging.getLogger("remote_storage")


class RemoteStorage:
    def __init__(self, remote: str, local_root: str = "data/archive",
                 rclone_bin: str = "rclone", extra_flags: Optional[list] = None):
        self.remote = (remote or "").strip()            # e.g. "gdrive:sp-trading-archive"
        self.local_root = local_root
        self.rclone = rclone_bin
        self.extra = extra_flags or ["--transfers", "8", "--checkers", "16"]
        self.enabled = bool(self.remote) and shutil.which(self.rclone) is not None
        if not self.enabled:
            logger.warning("RemoteStorage disabled (no remote or rclone missing) — local-only")

    def _run(self, args: list) -> bool:
        try:
            subprocess.run([self.rclone, *args, *self.extra],
                           check=True, capture_output=True, text=True, timeout=1200)
            return True
        except Exception as e:
            logger.warning("rclone %s failed: %s", args[:1], e)
            return False

    def sync_up(self, subpath: str = "") -> bool:          # archiver: cache -> remote
        if not self.enabled: return False
        src = os.path.join(self.local_root, subpath)
        dst = f"{self.remote}/{subpath}".rstrip("/")
        return self._run(["sync", src, dst])

    def sync_down(self, subpath: str = "") -> bool:        # consumer: remote -> cache
        if not self.enabled: return False
        src = f"{self.remote}/{subpath}".rstrip("/")
        dst = os.path.join(self.local_root, subpath)
        os.makedirs(dst, exist_ok=True)
        return self._run(["sync", src, dst])

    def fetch(self, remote_key: str) -> Optional[str]:     # on-demand single file
        local_path = os.path.join(self.local_root, remote_key)
        if os.path.exists(local_path):
            return local_path
        if not self.enabled:
            return None
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        ok = self._run(["copyto", f"{self.remote}/{remote_key}", local_path])
        return local_path if ok and os.path.exists(local_path) else None


_default: Optional[RemoteStorage] = None
def get_storage(config=None) -> RemoteStorage:
    global _default
    if _default is None:
        remote = (getattr(config, "STORAGE_REMOTE", None) if config
                  else None) or os.getenv("STORAGE_REMOTE", "")
        root = (getattr(config, "ARCHIVE_LOCAL_ROOT", None) if config
                else None) or os.getenv("ARCHIVE_LOCAL_ROOT", "data/archive")
        _default = RemoteStorage(remote, root)
    return _default


