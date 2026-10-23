import json
import shutil
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from qwen_voicebake.app.server import lines_from_disk, start_server
from qwen_voicebake.config import load_project

STARTER = Path(__file__).resolve().parents[1] / "examples" / "starter"


def _get(port: int, path: str):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as r:
        return r.status, json.loads(r.read())


def _post(port: int, path: str, body: bytes):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


@pytest.fixture
def server():
    calls = []

    def submit(line_id, seed):
        calls.append((line_id, seed))
        if line_id == "boom":
            raise RuntimeError("engine fell over")
        return {"ok": True, "path": f"/abs/{line_id}.ogg", "rel": f"v/{line_id}.ogg"}

    srv = start_server(
        0,
        lambda: {"project": "p", "model": "", "device": "", "busy": False, "queued": 0},
        lambda: [{"id": "a", "voice": "v", "tone": "warm", "state": "new", "path": None}],
        submit,
    )
    srv.calls = calls
    yield srv
    srv.stop()


def test_status_and_lines(server):
    code, body = _get(server.port, "/status")
    assert code == 200 and body["project"] == "p" and body["busy"] is False
    code, body = _get(server.port, "/lines")
    assert code == 200 and body[0]["id"] == "a"


def test_unknown_path_is_404(server):
    with pytest.raises(urllib.error.HTTPError) as e:
        _get(server.port, "/nope")
    assert e.value.code == 404


def test_regenerate_passes_line_and_seed(server):
    code, body = _post(server.port, "/regenerate", b'{"line_id": "x1", "seed": 9}')
    assert code == 200 and body["ok"] and body["rel"] == "v/x1.ogg"
    code, body = _post(server.port, "/regenerate", b'{"line_id": "x2"}')
    assert server.calls == [("x1", 9), ("x2", None)]


@pytest.mark.parametrize(
    "body",
    [b"not json", b"{}", b'{"line_id": ""}', b'{"line_id": "a", "seed": "3"}', b"[1]"],
)
def test_regenerate_rejects_bad_bodies(server, body):
    code, out = _post(server.port, "/regenerate", body)
    assert code == 400 and out["ok"] is False
    assert server.calls == []


def test_regenerate_reports_errors(server):
    code, out = _post(server.port, "/regenerate", b'{"line_id": "boom"}')
    assert code == 500 and "engine fell over" in out["error"]


def test_binds_loopback_only(server):
    assert server.server_address[0] == "127.0.0.1"


def test_lines_from_disk(tmp_path):
    root = tmp_path / "p"
    shutil.copytree(STARTER, root)
    rows = lines_from_disk(load_project(root))
    assert len(rows) == 12
    assert {r["state"] for r in rows} == {"new"}
    assert all(r["path"] is None for r in rows)
