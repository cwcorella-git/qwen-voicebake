"""Reading and writing the line list: JSON, CSV, or a user scanner script."""

from __future__ import annotations

import csv
import importlib.util
import json
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ._atomic import atomic_write_text
from .schema import Line

if TYPE_CHECKING:
    from .config import Project

CSV_FIELDS = ["id", "voice", "tone", "text", "kind", "direction"]


def _line_from_dict(d: dict[str, Any]) -> Line:
    def s(key: str, default: str = "") -> str:
        v = d.get(key)
        return default if v is None or str(v).strip() == "" and key != "text" else str(v)

    return Line(
        id=s("id").strip(),
        voice=s("voice").strip(),
        tone=s("tone", "neutral").strip(),
        text=s("text"),
        kind=s("kind", "speech").strip(),
        direction=s("direction").strip(),
    )


def load_lines_json(path: str | Path) -> list[Line]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    items = data["lines"] if isinstance(data, dict) else data
    return [_line_from_dict(d) for d in items]


def load_lines_csv(path: str | Path) -> list[Line]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return [_line_from_dict(row) for row in csv.DictReader(f)]


def save_lines_json(path: str | Path, lines: list[Line]) -> None:
    body = {"version": 1, "lines": [asdict(line) for line in lines]}
    atomic_write_text(path, json.dumps(body, indent=2, ensure_ascii=False) + "\n")


def csv_to_json(csv_path: str | Path, json_path: str | Path) -> list[Line]:
    lines = load_lines_csv(csv_path)
    save_lines_json(json_path, lines)
    return lines


def run_scanner(path: str | Path, project_dir: str | Path) -> list[Line]:
    """Load the scanner module at path and call scan(project_dir) -> list[dict]."""
    path = Path(path)
    spec = importlib.util.spec_from_file_location(f"_voicebake_scanner_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load scanner {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "scan"):
        raise AttributeError(f"scanner {path} has no scan(project_dir) function")
    return [_line_from_dict(d) for d in module.scan(Path(project_dir))]


def lines_source(project: Project) -> str:
    """Where lines come from: 'scanner', 'csv' or 'json'. Only 'json' is editable."""
    if project.paths.scanner is not None:
        return "scanner"
    if project.paths.lines.suffix.lower() == ".csv":
        return "csv"
    return "json"


def load_lines(project: Project) -> list[Line]:
    src = lines_source(project)
    if src == "scanner":
        assert project.paths.scanner is not None
        return run_scanner(project.paths.scanner, project.root)
    if src == "csv":
        return load_lines_csv(project.paths.lines)
    return load_lines_json(project.paths.lines)
