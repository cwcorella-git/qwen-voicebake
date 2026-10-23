"""Single-writer lock for a project directory, with a heartbeat."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

from ._atomic import atomic_write_text

HEARTBEAT_SECONDS = 5.0
STALE_SECONDS = 30.0


class LockHeld(RuntimeError):
    """Raised when another live process holds the project lock."""

    def __init__(self, holder: dict[str, Any]) -> None:
        super().__init__(f"project is locked by {holder.get('owner')} (pid {holder.get('pid')})")
        self.holder = holder


def _lock_path(root: str | Path) -> Path:
    return Path(root) / ".voicebake" / "lock"


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":  # pragma: no cover
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        code = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return bool(ok) and code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _read(path: Path) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _is_stale(data: dict[str, Any], now: float | None = None) -> bool:
    now = time.time() if now is None else now
    if now - float(data.get("heartbeat", 0)) > STALE_SECONDS:
        return True
    return not pid_alive(int(data.get("pid", 0)))


def holder(root: str | Path) -> dict[str, Any] | None:
    """Return the live lock holder's record, or None if unlocked or stale."""
    data = _read(_lock_path(root))
    if data is None or _is_stale(data):
        return None
    return data


class ProjectLock:
    def __init__(self, root: str | Path, owner: str) -> None:
        self.path = _lock_path(root)
        self.owner = owner
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.held = False

    def _write(self) -> None:
        body = {"pid": os.getpid(), "owner": self.owner, "heartbeat": time.time()}
        atomic_write_text(self.path, json.dumps(body))

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = _read(self.path)
        if data is not None and not _is_stale(data) and data.get("pid") != os.getpid():
            raise LockHeld(data)
        self._write()
        self.held = True
        self._stop.clear()
        self._thread = threading.Thread(target=self._beat, name="voicebake-lock", daemon=True)
        self._thread.start()

    def _beat(self) -> None:
        while not self._stop.wait(HEARTBEAT_SECONDS):
            try:
                self._write()
            except OSError:
                pass

    def release(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
        if self.held:
            data = _read(self.path)
            if data is not None and data.get("pid") == os.getpid():
                try:
                    self.path.unlink()
                except OSError:
                    pass
            self.held = False

    def __enter__(self) -> ProjectLock:
        self.acquire()
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()
