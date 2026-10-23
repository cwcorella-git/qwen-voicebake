"""Record of baked takes: which output file was made from which input hash."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ._atomic import atomic_write_text

if TYPE_CHECKING:
    from .schema import Line

LEDGER_VERSION = 1
HUMAN_SUFFIX = ".human"


def take_rel(line: Line, fmt: str) -> str:
    """Path of a line's take relative to the output directory (always forward slashes)."""
    return f"{line.voice}/{line.id}.{fmt}"


class Ledger:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.takes: dict[str, dict[str, Any]] = {}
        self.failed: dict[str, str] = {}

    @classmethod
    def for_root(cls, root: str | Path) -> Ledger:
        return cls.load(Path(root) / ".voicebake" / "ledger.json")

    @classmethod
    def load(cls, path: str | Path) -> Ledger:
        led = cls(path)
        if led.path.is_file():
            with open(led.path, encoding="utf-8") as f:
                data = json.load(f)
            led.takes = dict(data.get("takes", {}))
            led.failed = dict(data.get("failed", {}))
        return led

    def save(self) -> None:
        body = {"version": LEDGER_VERSION, "takes": self.takes, "failed": self.failed}
        atomic_write_text(self.path, json.dumps(body, indent=2, sort_keys=True) + "\n")

    def is_current(self, rel: str, h: str) -> bool:
        entry = self.takes.get(rel)
        return entry is not None and entry.get("hash") == h

    def stamp(
        self,
        rel: str,
        h: str,
        route: str,
        duration: float,
        qa: str = "ok",
        qa_reasons: list[str] | None = None,
    ) -> None:
        self.takes[rel] = {
            "hash": h,
            "route": route,
            "duration": round(float(duration), 3),
            "qa": qa,
            "qa_reasons": list(qa_reasons or []),
            "ts": time.time(),
        }
        self.failed.pop(rel, None)

    def mark_failed(self, rel: str, reason: str) -> None:
        self.failed[rel] = reason

    def line_state(
        self, line: Line, out_dir: str | Path, expected_hash: str | None, fmt: str = "ogg"
    ) -> str:
        """Return "human", "ok", "failed", "stale" or "new" for a line's take."""
        rel = take_rel(line, fmt)
        out_file = Path(out_dir) / rel
        if Path(str(out_file) + HUMAN_SUFFIX).exists():
            return "human"
        if out_file.is_file() and expected_hash is not None and self.is_current(rel, expected_hash):
            return "ok"
        if rel in self.failed:
            return "failed"
        if out_file.is_file() or rel in self.takes:
            return "stale"
        return "new"
