"""Local HTTP endpoint for editor integrations. Listens on 127.0.0.1 only and never touches Qt.

GET  /status      -> {project, model, device, busy, queued}
GET  /lines       -> [{id, voice, tone, state, path}]
POST /regenerate  {"line_id": "...", "seed": optional int}
                  -> {ok, path, rel, route, qa, duration} or {ok: false, error}
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

StatusFn = Callable[[], dict[str, Any]]
LinesFn = Callable[[], list[dict[str, Any]]]
SubmitFn = Callable[[str, "int | None"], dict[str, Any]]

MAX_BODY = 64 * 1024


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

    def do_GET(self) -> None:  # noqa: N802
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
        self, port: int, status_fn: StatusFn, lines_fn: LinesFn, submit_fn: SubmitFn
    ) -> None:
        self.status_fn = status_fn
        self.lines_fn = lines_fn
        self.submit_fn = submit_fn
        super().__init__(("127.0.0.1", port), _Handler)
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        return int(self.server_address[1])

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self.serve_forever, name="voicebake-http", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self.shutdown()
        self.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)


def start_server(
    port: int, status_fn: StatusFn, lines_fn: LinesFn, submit_fn: SubmitFn
) -> VoicebakeHTTPServer:
    """Bind and serve in a daemon thread. Raises OSError if the port is taken."""
    srv = VoicebakeHTTPServer(port, status_fn, lines_fn, submit_fn)
    srv.start()
    return srv
