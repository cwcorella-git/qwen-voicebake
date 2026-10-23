"""Example line scanner: finds say("voice", "id", "tone", "text") calls in game/*.gd.

To use it, set  scanner = "tools/example_scanner.py"  under [paths] in voicebake.toml.
voicebake calls scan(project_dir) and expects a list of dicts with the same keys as a line
in lines.json: id, voice, tone, text, and optionally kind and direction.
"""

from __future__ import annotations

import re
from pathlib import Path

SAY_RE = re.compile(
    r'say\(\s*"(?P<voice>[^"]+)"\s*,\s*"(?P<id>[^"]+)"\s*,\s*"(?P<tone>[^"]+)"\s*,'
    r'\s*"(?P<text>(?:[^"\\]|\\.)*)"\s*\)'
)


def scan(project_dir: Path) -> list[dict]:
    lines: list[dict] = []
    for path in sorted(Path(project_dir, "game").rglob("*.gd")):
        source = path.read_text(encoding="utf-8")
        for m in SAY_RE.finditer(source):
            lines.append(
                {
                    "id": m["id"],
                    "voice": m["voice"],
                    "tone": m["tone"],
                    "text": m["text"].replace('\\"', '"'),
                }
            )
    return lines
