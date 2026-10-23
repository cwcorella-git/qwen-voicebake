"""Atomic file writes: write a temp file in the same directory, then os.replace."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import IO, Any


def atomic_write(path: str | os.PathLike[str], writer: Callable[[str], Any]) -> None:
    """Call writer(tmp_path) and move the result onto path. The temp keeps path's suffix."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=path.suffix or ".tmp")
    os.close(fd)
    try:
        writer(tmp)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_write_text(path: str | os.PathLike[str], text: str) -> None:
    def _w(tmp: str) -> None:
        f: IO[str]
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)

    atomic_write(path, _w)


def atomic_write_bytes(path: str | os.PathLike[str], data: bytes) -> None:
    def _w(tmp: str) -> None:
        with open(tmp, "wb") as f:
            f.write(data)

    atomic_write(path, _w)
