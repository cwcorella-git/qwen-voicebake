"""Data model: voices, lines, issues, and validation."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ._atomic import atomic_write_text

if TYPE_CHECKING:
    from .config import Project

KINDS = ("speech", "vocal")
ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


@dataclass
class Voice:
    name: str
    instruct: str
    ref_text: str
    seed: int = 1234
    temperature: float | None = None
    language: str | None = None


@dataclass
class Line:
    id: str
    voice: str
    tone: str
    text: str
    kind: str = "speech"
    direction: str = ""


@dataclass
class Issue:
    level: str  # "error" or "warning"
    where: str
    msg: str

    def __str__(self) -> str:
        return f"{self.level}: {self.where}: {self.msg}"


def load_voices(path: str | Path) -> dict[str, Voice]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    out: dict[str, Voice] = {}
    for name, v in data.get("voices", {}).items():
        out[name] = Voice(
            name=name,
            instruct=v.get("instruct", ""),
            ref_text=v.get("ref_text", ""),
            seed=int(v.get("seed", 1234)),
            temperature=v.get("temperature"),
            language=v.get("language"),
        )
    return out


def save_voices(path: str | Path, voices: dict[str, Voice]) -> None:
    body = {}
    for name, v in voices.items():
        d = asdict(v)
        d.pop("name")
        body[name] = d
    text = json.dumps({"version": 1, "voices": body}, indent=2, ensure_ascii=False)
    atomic_write_text(path, text + "\n")


def validate(
    project: Project,
    voices: dict[str, Voice],
    lines: list[Line],
    tones: dict[str, str],
) -> list[Issue]:
    issues: list[Issue] = []
    for name in voices:
        if not ID_RE.match(name):
            issues.append(Issue("error", name, "voice name may only contain A-Z a-z 0-9 _ . -"))
    seen: set[str] = set()
    for line in lines:
        where = line.id or "(no id)"
        if not line.id:
            issues.append(Issue("error", where, "empty id"))
        elif not ID_RE.match(line.id):
            issues.append(Issue("error", where, "id may only contain A-Z a-z 0-9 _ . -"))
        if line.id in seen:
            issues.append(Issue("error", where, "duplicate id"))
        seen.add(line.id)
        if line.voice not in voices:
            issues.append(Issue("error", where, f"unknown voice '{line.voice}'"))
        if line.tone not in tones:
            issues.append(Issue("error", where, f"unknown tone '{line.tone}'"))
        if line.kind not in KINDS:
            issues.append(Issue("error", where, f"kind must be one of {', '.join(KINDS)}"))
        if not line.text.strip():
            issues.append(Issue("error", where, "empty text"))
    return issues
