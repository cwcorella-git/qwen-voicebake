import json
from pathlib import Path

import pytest

from qwen_voicebake.config import load_project


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    (tmp_path / "voicebake.toml").write_text("", encoding="utf-8")
    voices = {
        "version": 1,
        "voices": {"mech": {"instruct": "A gruff man.", "ref_text": "Hello.", "seed": 7}},
    }
    (tmp_path / "voices.json").write_text(json.dumps(voices), encoding="utf-8")
    return tmp_path


@pytest.fixture
def project(project_dir: Path):
    return load_project(project_dir)


SAMPLE_LINES = [
    {"id": "m_hello", "voice": "mech", "tone": "warm", "text": "Back again, are you?"},
    {"id": "m_angry", "voice": "mech", "tone": "anger", "text": "Put that down right now."},
    {"id": "m_grunt", "voice": "mech", "tone": "neutral", "text": "Hnngh!", "kind": "vocal"},
    {
        "id": "m_dir",
        "voice": "mech",
        "tone": "warm",
        "text": "Over here, quickly now.",
        "direction": "Calling from far away.",
    },
    {"id": "c_hi", "voice": "clerk", "tone": "nervous", "text": "Sorry, can I help you?"},
]


def write_lines(root: Path, lines: list[dict]) -> None:
    (root / "lines.json").write_text(json.dumps({"version": 1, "lines": lines}), encoding="utf-8")


@pytest.fixture
def bake_project(project_dir: Path):
    voices = {
        "version": 1,
        "voices": {
            "mech": {"instruct": "A gruff man.", "ref_text": "Hello there friend.", "seed": 7},
            "clerk": {"instruct": "A nervous woman.", "ref_text": "Good morning to you."},
        },
    }
    (project_dir / "voices.json").write_text(json.dumps(voices), encoding="utf-8")
    write_lines(project_dir, SAMPLE_LINES)
    return load_project(project_dir)
