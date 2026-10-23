"""Local HTTP endpoint for editor integrations. Listens on 127.0.0.1 only and never touches Qt.

Every request needs `Authorization: Bearer <token>`. The token is random per app session and
written, with the port, to `<out>/.voicebake-session` (JSON, owner-readable only), which is
removed on shutdown. Requests with an Origin header or a Host other than 127.0.0.1:<port> or
localhost:<port> are refused, so web pages cannot drive the server (CSRF, DNS rebinding).

GET  /status      -> {project, model, device, busy, queued}
GET  /lines       -> [{id, voice, tone, state, path}]
POST /regenerate  {"line_id": "...", "seed": optional int}
                  -> {ok, path, rel, route, qa, duration} or {ok: false, error}
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
import stat
import tempfile
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from ..schema import ID_RE

StatusFn = Callable[[], dict[str, Any]]
LinesFn = Callable[[], list[dict[str, Any]]]
SubmitFn = Callable[[str, "int | None"], dict[str, Any]]

MAX_BODY = 64 * 1024
SESSION_FILE = ".voicebake-session"


class SessionFileError(OSError):
    """The session file could not be written privately."""


def lines_from_disk(project: Any) -> list[dict[str, Any]]:
    """Line states computed from the saved project files (safe to call from any thread)."""
    from ..ledger import Ledger, take_rel
    from ..lines_io import load_lines
    from ..planner import plan
    from ..schema import load_voices
    from ..tones import load_project_tones

    voices = load_voices(project.paths.voices)
    tones = load_project_tones(project)
    lines = [ln for ln in load_lines(project) if ln.voice in voices and ln.tone in tones]
    p = plan(project, voices, lines, tones, Ledger.for_root(project.root))
    states = {j.line.id: j.state for j in p.jobs}
    states.update({lid: "ok" for lid in p.up_to_date})
    states.update({lid: "human" for lid in p.skipped_human})
    out = []
    for ln in lines:
        path = project.paths.out / take_rel(ln, project.paths.format)
        out.append(
            {
                "id": ln.id,
                "voice": ln.voice,
                "tone": ln.tone,
                "state": states.get(ln.id, "new"),
                "path": str(path) if path.is_file() else None,
            }
        )
    return out


class _Handler(BaseHTTPRequestHandler):
    server: VoicebakeHTTPServer

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - quiet by default
        pass

    def _send(self, code: int, body: Any) -> None:
        data = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _allowed(self) -> bool:
        """Check Host, Origin and token. Sends the error response and returns False if not."""
        port = self.server.port
        if self.headers.get("Host") not in (f"127.0.0.1:{port}", f"localhost:{port}"):
            self._send(403, {"ok": False, "error": "bad host"})
            return False
        if self.headers.get("Origin") is not None:
            self._send(403, {"ok": False, "error": "browser requests are not allowed"})
            return False
        auth = self.headers.get("Authorization") or ""
        expected = f"Bearer {self.server.token}"
        if not hmac.compare_digest(auth.encode("utf-8"), expected.encode("utf-8")):
            self._send(401, {"ok": False, "error": "missing or wrong token"})
            return False
        return True

    def do_GET(self) -> None:  # noqa: N802
        if not self._allowed():
            return
        path = self.path.split("?", 1)[0]
        try:
            if path == "/status":
                self._send(200, self.server.status_fn())
            elif path == "/lines":
                self._send(200, self.server.lines_fn())
            else:
                self._send(404, {"ok": False, "error": "not found"})
        except Exception as e:  # noqa: BLE001
            self._send(500, {"ok": False, "error": f"{type(e).__name__}: {e}"})

    def do_POST(self) -> None:  # noqa: N802
        if not self._allowed():
            return
        ctype = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        if ctype != "application/json":
            self._send(415, {"ok": False, "error": "Content-Type must be application/json"})
            return
        if self.path.split("?", 1)[0] != "/regenerate":
            self._send(404, {"ok": False, "error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                raise ValueError("body too large")
            body = json.loads(self.rfile.read(length) or b"{}")
            line_id = body.get("line_id")
            if not isinstance(line_id, str) or not line_id:
                raise ValueError("line_id is required")
            if not ID_RE.match(line_id):
                raise ValueError("line_id may only contain A-Z a-z 0-9 _ . -")
            seed = body.get("seed")
            if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int)):
                raise ValueError("seed must be an integer")
        except (ValueError, AttributeError) as e:
            self._send(400, {"ok": False, "error": str(e)})
            return
        try:
            self._send(200, self.server.submit_fn(line_id, seed))
        except Exception as e:  # noqa: BLE001
            self._send(500, {"ok": False, "error": f"{type(e).__name__}: {e}"})


class VoicebakeHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        port: int,
        status_fn: StatusFn,
        lines_fn: LinesFn,
        submit_fn: SubmitFn,
        token: str | None = None,
        session_dir: str | Path | None = None,
    ) -> None:
        self.token = token or secrets.token_urlsafe(32)
        self.session_dir = Path(session_dir) if session_dir is not None else None
        self.session_file: Path | None = None
        self.status_fn = status_fn
        self.lines_fn = lines_fn
        self.submit_fn = submit_fn
        super().__init__(("127.0.0.1", port), _Handler)
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        return int(self.server_address[1])

    def _write_session_file(self) -> None:
        """Write port and token to a private file. On POSIX the file must end up mode 0600,
        otherwise SessionFileError is raised and the server must not run."""
        if self.session_dir is None:
            return
        self.session_dir.mkdir(parents=True, exist_ok=True)
        path = self.session_dir / SESSION_FILE
        # mkstemp: random name, O_EXCL, mode 0600 from the start.
        fd, tmp_name = tempfile.mkstemp(
            dir=self.session_dir, prefix=SESSION_FILE + ".", suffix=".tmp"
        )
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"port": self.port, "token": self.token}, f)
                f.flush()
                os.fsync(f.fileno())
            if os.name == "posix":
                os.chmod(tmp, 0o600)
                mode = stat.S_IMODE(os.stat(tmp).st_mode)
                if mode != 0o600:
                    raise SessionFileError(
                        f"{path} would be readable by others (mode {mode:o}); "
                        "the local server was not started"
                    )
            os.replace(tmp, path)
        except BaseException:
            try:
                tmp.unlink()
            except OSError:
                pass
            raise
        self.session_file = path

    def start(self) -> None:
        self._write_session_file()
        self._thread = threading.Thread(
            target=self.serve_forever, name="voicebake-http", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self.shutdown()
        self.server_close()
        if self.session_file is not None:
            try:
                self.session_file.unlink()
            except OSError:
                pass
            self.session_file = None
        if self._thread is not None:
            self._thread.join(timeout=2)


def start_server(
    port: int,
    status_fn: StatusFn,
    lines_fn: LinesFn,
    submit_fn: SubmitFn,
    token: str | None = None,
    session_dir: str | Path | None = None,
) -> VoicebakeHTTPServer:
    """Bind and serve in a daemon thread. Raises OSError if the port is taken.

    session_dir (normally paths.out) receives the session file with the port and token.
    """
    srv = VoicebakeHTTPServer(port, status_fn, lines_fn, submit_fn, token, session_dir)
    try:
        srv.start()
    except BaseException:
        srv.server_close()
        raise
    return srv
