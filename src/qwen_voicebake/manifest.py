"""manifest.json in the output directory: what exists, for game-side lookup."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from ._atomic import atomic_write_text
from .ledger import Ledger, take_rel
from .planner import route_for

if TYPE_CHECKING:
    from pathlib import Path

    from .config import Project
    from .schema import Line, Voice

MANIFEST_NAME = "manifest.json"


def build_manifest(project: Project, voices: dict[str, Voice], lines: list[Line], ledger: Ledger):
    fmt = project.paths.format
    out: dict[str, dict[str, dict]] = {}
    for line in lines:
        rel = take_rel(line, fmt)
        if not (project.paths.out / rel).is_file():
            continue
        entry = ledger.takes.get(rel, {})
        out.setdefault(line.voice, {})[line.id] = {
            "path": rel,
            "text": line.text,
            "tone": line.tone,
            "route": entry.get("route", route_for(line)),
            "duration": entry.get("duration"),
        }
    return {"version": 1, "format": fmt, "voices": out}


def write_manifest(
    project: Project, voices: dict[str, Voice], lines: list[Line], ledger: Ledger
) -> Path:
    path = project.paths.out / MANIFEST_NAME
    body = build_manifest(project, voices, lines, ledger)
    atomic_write_text(path, json.dumps(body, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    return path
