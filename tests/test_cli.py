import filecmp
import json
import subprocess
import sys
from pathlib import Path

import pytest

import qwen_voicebake
from qwen_voicebake import cli

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / "examples" / "starter"
TEMPLATE = Path(qwen_voicebake.__file__).parent / "templates" / "starter"


@pytest.fixture
def starter(tmp_path: Path, capsys) -> Path:
    dest = tmp_path / "proj"
    assert cli.main(["init", str(dest)]) == 0
    capsys.readouterr()
    return dest


def _files(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def test_init_scaffolds(starter: Path):
    for name in ("voicebake.toml", "voices.json", "lines.json", "tones.toml"):
        assert (starter / name).is_file()
    assert (starter / "tools" / "example_scanner.py").is_file()
    assert list((starter / "game").glob("*.gd"))
    assert cli.main(["init", str(starter)]) == 2


def test_init_refuses_to_overwrite_files(tmp_path: Path):
    (tmp_path / "lines.json").write_text("{}", encoding="utf-8")
    assert cli.main(["init", str(tmp_path)]) == 2
    assert (tmp_path / "lines.json").read_text(encoding="utf-8") == "{}"


def test_template_matches_example():
    ex = {f for f in _files(EXAMPLE) if f != "README.md" and "__pycache__" not in f}
    tp = {f for f in _files(TEMPLATE) if f != "README.md" and "__pycache__" not in f}
    assert ex == tp
    for f in ex:
        assert filecmp.cmp(EXAMPLE / f, TEMPLATE / f, shallow=False), f


def test_starter_shape():
    lines = json.loads((EXAMPLE / "lines.json").read_text(encoding="utf-8"))["lines"]
    assert len(lines) == 12
    assert sum(1 for ln in lines if ln["kind"] == "vocal") == 2
    assert sum(1 for ln in lines if ln["direction"]) == 1


def test_check_passes_on_starter(starter: Path, capsys):
    assert cli.main(["check", "--project", str(starter), "--strict"]) == 0
    assert "0 error(s), 0 warning(s)" in capsys.readouterr().out


def test_check_fails_on_errors(starter: Path):
    lines = json.loads((starter / "lines.json").read_text(encoding="utf-8"))
    lines["lines"][0]["voice"] = "nobody"
    (starter / "lines.json").write_text(json.dumps(lines), encoding="utf-8")
    assert cli.main(["check", "--project", str(starter)]) == 1


def test_project_discovered_from_cwd(starter: Path, monkeypatch, capsys):
    sub = starter / "game"
    monkeypatch.chdir(sub)
    assert cli.main(["check"]) == 0
    monkeypatch.chdir(starter.parent)
    assert cli.main(["check"]) == 2


def test_scanner_finds_sample_calls(starter: Path):
    from qwen_voicebake.lines_io import run_scanner

    found = run_scanner(starter / "tools" / "example_scanner.py", starter)
    assert [ln.id for ln in found] == ["mech_greet_01", "mech_warn_01", "ann_dock_01"]


def test_bake_fake(starter: Path, capsys):
    assert cli.main(["bake", "--fake", "--project", str(starter)]) == 0
    out = capsys.readouterr().out
    assert "baked 12, failed 0" in out
    assert (starter / "voice" / "mechanic" / "mech_greet_01.ogg").is_file()
    manifest = json.loads((starter / "voice" / "manifest.json").read_text(encoding="utf-8"))
    assert sum(len(v) for v in manifest["voices"].values()) == 12
    assert cli.main(["bake", "--fake", "--project", str(starter)]) == 0
    assert "baked 0" in capsys.readouterr().out
    assert cli.main(["status", "--project", str(starter)]) == 0
    assert "ok      12" in capsys.readouterr().out


def test_bake_dry_run_lists_routes_and_writes_nothing(starter: Path, capsys):
    assert cli.main(["bake", "--dry-run", "--project", str(starter), "--voices", "mechanic"]) == 0
    out = capsys.readouterr().out
    assert "design  mech_grunt_01" in out
    assert "clone   mech_greet_01" in out
    assert "dry run: 4 to bake" in out
    assert not (starter / "voice").exists()
    assert not (starter / "refs").exists()


def test_dry_run_does_not_import_torch(starter: Path):
    code = (
        "import sys; from qwen_voicebake import cli; "
        f"rc = cli.main(['bake', '--dry-run', '--project', {str(starter)!r}]); "
        "assert rc == 0 and 'torch' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True)


def test_bake_exit_3_when_locked(starter: Path, capsys):
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import sys, time; from qwen_voicebake.lockfile import ProjectLock; "
            "l = ProjectLock(sys.argv[1], 'other'); l.acquire(); print('ready', flush=True); "
            "time.sleep(60)",
            str(starter),
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout.readline().strip() == "ready"
        assert cli.main(["bake", "--fake", "--project", str(starter)]) == 3
    finally:
        holder.kill()
        holder.wait()
    assert "locked" in capsys.readouterr().err
    assert not (starter / "voice" / "manifest.json").exists()


def test_bake_limit_and_line_glob(starter: Path, capsys):
    assert (
        cli.main(["bake", "--fake", "--lines", "ann_*", "--limit", "2", "--project", str(starter)])
        == 0
    )
    assert "baked 2," in capsys.readouterr().out


def test_refs_flow_fake(starter: Path, capsys):
    p = str(starter)
    assert cli.main(["refs", "status", "--project", p, "--voice", "mechanic"]) == 0
    assert "missing" in capsys.readouterr().out

    assert (
        cli.main(
            ["refs", "candidates", "mechanic", "warm", "--seeds", "1,2", "--fake", "--project", p]
        )
        == 0
    )
    capsys.readouterr()
    cands = starter / ".voicebake" / "candidates" / "mechanic" / "warm"
    assert {f.name for f in cands.iterdir()} == {"seed1.ogg", "seed2.ogg"}

    assert cli.main(["refs", "pick", "mechanic", "warm", "2", "--project", p]) == 0
    assert (starter / "refs" / "mechanic" / "warm.ogg").is_file()
    capsys.readouterr()
    cli.main(["refs", "status", "--project", p, "--voice", "mechanic"])
    assert "mechanic/warm" in capsys.readouterr().out
    assert cli.main(["refs", "unpin", "mechanic", "warm", "--project", p]) == 0
    assert cli.main(["refs", "pin", "mechanic", "warm", "--project", p]) == 0
    lock = json.loads((starter / "refs" / "refs.lock.json").read_text(encoding="utf-8"))
    assert lock["mechanic/warm"]["pinned"] is True and lock["mechanic/warm"]["seed"] == 2


def test_refs_unknown_voice_is_usage_error(starter: Path):
    assert cli.main(["refs", "pick", "ghost", "warm", "1", "--project", str(starter)]) == 2


def test_usage_error_exit_2():
    with pytest.raises(SystemExit) as e:
        cli.main(["bake", "--bogus"])
    assert e.value.code == 2
