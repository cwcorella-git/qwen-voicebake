import json
import os
import subprocess
import sys
import time

import pytest

from qwen_voicebake.lockfile import LockHeld, ProjectLock, holder


def _write(root, pid, age=0.0):
    p = root / ".voicebake" / "lock"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"pid": pid, "owner": "other", "heartbeat": time.time() - age}))


def test_acquire_release(tmp_path):
    with ProjectLock(tmp_path, "me") as lock:
        h = holder(tmp_path)
        assert h is not None and h["pid"] == os.getpid() and h["owner"] == "me"
        assert lock.held
    assert holder(tmp_path) is None
    assert not (tmp_path / ".voicebake" / "lock").exists()


def test_held_raises(tmp_path):
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        _write(tmp_path, proc.pid)
        with pytest.raises(LockHeld):
            ProjectLock(tmp_path, "me").acquire()
    finally:
        proc.kill()
        proc.wait()


def test_dead_pid_reclaimed(tmp_path):
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    _write(tmp_path, proc.pid)
    assert holder(tmp_path) is None
    with ProjectLock(tmp_path, "me"):
        assert holder(tmp_path)["owner"] == "me"


def test_old_heartbeat_reclaimed(tmp_path):
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        _write(tmp_path, proc.pid, age=120)
        with ProjectLock(tmp_path, "me"):
            assert holder(tmp_path)["owner"] == "me"
    finally:
        proc.kill()
        proc.wait()


def test_fresh_create_is_exclusive(tmp_path):
    a = ProjectLock(tmp_path, "a")
    (tmp_path / ".voicebake").mkdir()
    assert a._create() is True
    assert ProjectLock(tmp_path, "b")._create() is False
