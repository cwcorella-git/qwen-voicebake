import json

from qwen_voicebake.lines_io import (
    csv_to_json,
    lines_source,
    load_lines,
    run_scanner,
    save_lines_json,
)
from qwen_voicebake.schema import Line

CSV = (
    "id,voice,tone,text,kind,direction\n"
    "a1,mech,warm,Back again?,speech,\n"
    'a2,mech,,"Hnngh!",vocal,groaning\n'
)


def test_json_csv_parity(project):
    project.paths.lines.write_text(
        json.dumps(
            {
                "version": 1,
                "lines": [
                    {"id": "a1", "voice": "mech", "tone": "warm", "text": "Back again?"},
                    {
                        "id": "a2",
                        "voice": "mech",
                        "text": "Hnngh!",
                        "kind": "vocal",
                        "direction": "groaning",
                    },
                ],
            }
        )
    )
    from_json = load_lines(project)
    csv_path = project.root / "lines.csv"
    csv_path.write_text(CSV)
    project.paths.lines = csv_path
    assert lines_source(project) == "csv"
    assert load_lines(project) == from_json


def test_defaults():
    from qwen_voicebake.lines_io import _line_from_dict

    line = _line_from_dict({"id": "x", "voice": "v", "text": "Hi"})
    assert line == Line("x", "v", "neutral", "Hi", "speech", "")


def test_save_and_csv_to_json(tmp_path):
    csv_path = tmp_path / "l.csv"
    csv_path.write_text(CSV)
    out = tmp_path / "l.json"
    lines = csv_to_json(csv_path, out)
    data = json.loads(out.read_text())
    assert data["version"] == 1 and len(data["lines"]) == 2
    save_lines_json(tmp_path / "m.json", lines)
    assert json.loads((tmp_path / "m.json").read_text()) == data


def test_scanner_hook(project):
    scanner = project.root / "scan.py"
    scanner.write_text(
        "def scan(project_dir):\n"
        "    return [{'id': 's1', 'voice': 'mech', 'tone': 'fear', 'text': 'Run.'}]\n"
    )
    assert run_scanner(scanner, project.root)[0].tone == "fear"
    project.paths.scanner = scanner
    assert lines_source(project) == "scanner"
    assert [ln.id for ln in load_lines(project)] == ["s1"]
