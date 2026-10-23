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
