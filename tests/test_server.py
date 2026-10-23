import json
import os
import shutil
import stat
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from qwen_voicebake.app.server import lines_from_disk, start_server
from qwen_voicebake.config import load_project

STARTER = Path(__file__).resolve().parents[1] / "examples" / "starter"


TOKEN = "test-token"


def _request(port, path, body=None, headers=None, token=TOKEN, method=None):
    h = {"Host": f"127.0.0.1:{port}"}
    if token is not None:
        h["Authorization"] = f"Bearer {token}"
    if body is not None:
        h["Content-Type"] = "application/json"
    h.update(headers or {})
    h = {k: v for k, v in h.items() if v is not None}
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=body, headers=h)
    if method:
        req.method = method
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _get(port, path, **kw):
    return _request(port, path, **kw)


def _post(port, path, body, **kw):
    return _request(port, path, body=body, **kw)


@pytest.fixture
def server(tmp_path):
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
        token=TOKEN,
        session_dir=tmp_path / "out",
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
    code, _ = _get(server.port, "/nope")
    assert code == 404


def test_regenerate_passes_line_and_seed(server):
    code, body = _post(server.port, "/regenerate", b'{"line_id": "x1", "seed": 9}')
    assert code == 200 and body["ok"] and body["rel"] == "v/x1.ogg"
    code, body = _post(server.port, "/regenerate", b'{"line_id": "x2"}')
    assert server.calls == [("x1", 9), ("x2", None)]


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b"{}",
        b'{"line_id": ""}',
        b'{"line_id": "a", "seed": "3"}',
        b"[1]",
        b'{"line_id": "../evil"}',
        b'{"line_id": "a/b"}',
    ],
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


@pytest.mark.parametrize("path", ["/status", "/lines"])
def test_get_requires_token(server, path):
    assert _get(server.port, path, token=None)[0] == 401
    assert _get(server.port, path, token="wrong")[0] == 401


def test_post_requires_token(server):
    code, out = _post(server.port, "/regenerate", b'{"line_id": "a"}', token="nope")
    assert code == 401 and out["ok"] is False
    assert server.calls == []


@pytest.mark.parametrize("host", ["evil.example:80", "127.0.0.1", "localhost:1"])
def test_rejects_foreign_host(server, host):
    code, out = _get(server.port, "/status", headers={"Host": host})
    assert code == 403 and out["ok"] is False


def test_accepts_localhost_host(server):
    code, _ = _get(server.port, "/status", headers={"Host": f"localhost:{server.port}"})
    assert code == 200


def test_rejects_any_origin(server):
    code, _ = _get(server.port, "/status", headers={"Origin": "http://127.0.0.1"})
    assert code == 403
    code, _ = _post(server.port, "/regenerate", b'{"line_id": "a"}', headers={"Origin": "null"})
    assert code == 403
    assert server.calls == []


def test_post_requires_json_content_type(server):
    code, out = _post(
        server.port, "/regenerate", b'{"line_id": "a"}', headers={"Content-Type": "text/plain"}
    )
    assert code == 415 and out["ok"] is False
    assert server.calls == []


def test_session_file_written_and_removed(tmp_path):
    srv = start_server(0, dict, list, lambda *_: {}, session_dir=tmp_path / "out")
    f = tmp_path / "out" / ".voicebake-session"
    data = json.loads(f.read_text(encoding="utf-8"))
    assert data == {"port": srv.port, "token": srv.token}
    assert len(srv.token) >= 40
    if os.name == "posix":
        assert stat.S_IMODE(f.stat().st_mode) == 0o600
    assert _get(srv.port, "/status", token=srv.token)[0] == 200
    srv.stop()
    assert not f.exists()


def test_tokens_differ_per_session(tmp_path):
    a = start_server(0, dict, list, lambda *_: {})
    b = start_server(0, dict, list, lambda *_: {})
    try:
        assert a.token != b.token
    finally:
        a.stop()
        b.stop()


def test_session_file_uses_private_temp_file(tmp_path, monkeypatch):
    import tempfile

    made = []
    real = tempfile.mkstemp

    def spy(*a, **k):
        made.append(k)
        return real(*a, **k)

    monkeypatch.setattr(tempfile, "mkstemp", spy)
    srv = start_server(0, dict, list, lambda *_: {}, session_dir=tmp_path)
    srv.stop()
    assert made and made[0]["dir"] == tmp_path and made[0]["prefix"] == ".voicebake-session."
    assert list(tmp_path.iterdir()) == []  # no temp files left behind


@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions")
def test_server_refuses_to_start_if_session_file_not_private(tmp_path, monkeypatch):
    from qwen_voicebake.app import server as server_mod

    real_stat = os.stat

    class Loose:
        def __init__(self, st):
            self.st_mode = (st.st_mode & ~0o777) | 0o644

    monkeypatch.setattr(
        server_mod.os,
        "stat",
        lambda p, *a, **k: Loose(real_stat(p)) if ".tmp" in str(p) else real_stat(p, *a, **k),
    )
    with pytest.raises(server_mod.SessionFileError):
        start_server(0, dict, list, lambda *_: {}, session_dir=tmp_path)
    assert list(tmp_path.iterdir()) == []
