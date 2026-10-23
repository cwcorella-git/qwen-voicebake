"""Engine work off the GUI thread: one QThread draining a queue of plain-dict jobs.

The engine (and torch, for the real one) is created and used only inside the worker thread.
Jobs can come from the GUI (submit) or from the local HTTP server (call, which blocks).
"""

from __future__ import annotations

import itertools
import queue
import threading
from dataclasses import asdict, dataclass, field
from typing import Any

from PySide6.QtCore import QObject, QThread, QTimer, Signal

from ..config import Project

JOB_KINDS = ("bake", "regenerate", "candidates")


@dataclass
class Job:
    kind: str
    payload: dict[str, Any]
    reply_id: int
    done: threading.Event = field(default_factory=threading.Event)
    result: dict[str, Any] | None = None
    error: str | None = None
    started: bool = False
    cancelled: bool = False


class EngineWorker(QObject):
    """Runs Baker and refs functions for the open project, one job at a time."""

    event = Signal(object)  # bake/refs event dicts
    progress = Signal(int, int)
    job_started = Signal(int, str)
    job_done = Signal(int, object)
    job_failed = Signal(int, str)
    model_changed = Signal(str, str)  # loaded model, device info
    busy_changed = Signal(bool)

    def __init__(self, project: Project, fake: bool = False) -> None:
        super().__init__()
        self.project = project
        self.fake = fake
        self.engine: Any = None
        self._queue: queue.Queue[Job | None] = queue.Queue()
        self._ids = itertools.count(1)
        self._cancel = threading.Event()
        self._lock = threading.Lock()
        self._busy = False
        self._model = ""
        self._device = ""
        self._thread = QThread()
        self._thread.setObjectName("voicebake-engine")
        self.moveToThread(self._thread)
        self._thread.started.connect(self._loop)

    # -- control (any thread) -----------------------------------------------------------

    def start(self) -> None:
        self._thread.start()

    def stop_async(self) -> None:
        """Ask the thread to end after the current job (the cancel flag stops a bake early)."""
        self._cancel.set()
        self._queue.put(None)

    def wait(self, timeout_ms: int) -> bool:
        """True once the worker thread has ended."""
        return self._thread.wait(timeout_ms)

    def stop(self) -> None:
        """Stop and block until the thread has ended. There is no timeout on purpose: the
        project lock must not be released while a take is still being written."""
        self.stop_async()
        self._thread.wait()

    def submit(self, kind: str, payload: dict[str, Any] | None = None) -> int:
        return self._enqueue(kind, payload).reply_id

    def call(self, kind: str, payload: dict[str, Any], timeout: float = 300.0) -> dict[str, Any]:
        """Enqueue a job and block until it finishes (for the HTTP server thread)."""
        job = self._enqueue(kind, payload)
        if not job.done.wait(timeout):
            with self._lock:
                if not job.started:
                    job.cancelled = True  # still queued: the worker loop skips it
                    return {"ok": False, "error": "timed out waiting for the engine; cancelled"}
            return {
                "ok": False,
                "error": "timed out; the line may still finish and appear in the manifest",
            }
        if job.error is not None:
            return {"ok": False, "error": job.error}
        return job.result or {}

    def _enqueue(self, kind: str, payload: dict[str, Any] | None) -> Job:
        if kind not in JOB_KINDS:
            raise ValueError(f"unknown job kind '{kind}'")
        job = Job(kind, dict(payload or {}), next(self._ids))
        self._queue.put(job)
        return job

    def cancel(self) -> None:
        """Stop the running bake after the current take, and drop queued jobs."""
        self._cancel.set()
        while True:
            try:
                job = self._queue.get_nowait()
            except queue.Empty:
                break
            if job is None:
                self._queue.put(None)
                break
            job.error = "cancelled"
            job.done.set()

    @property
    def busy(self) -> bool:
        return self._busy

    def queued(self) -> int:
        return self._queue.qsize()

    @property
    def model(self) -> str:
        return self._model

    @property
    def device(self) -> str:
        return self._device

    # -- worker thread --------------------------------------------------------------------

    def _loop(self) -> None:
        while True:
            job = self._queue.get()
            if job is None:
                break
            with self._lock:
                if job.cancelled:
                    skip = True
                else:
                    job.started = True
                    skip = False
            if skip:
                job.error = "cancelled"
                job.done.set()
                continue
            self._cancel.clear()
            self._set_busy(True)
            self.job_started.emit(job.reply_id, job.kind)
            try:
                job.result = self._run(job)
            except Exception as e:  # noqa: BLE001 - report every failure to the GUI
                job.error = f"{type(e).__name__}: {e}"
            finally:
                self._report_model()
                job.done.set()
            if job.error is not None:
                self.job_failed.emit(job.reply_id, job.error)
            else:
                self.job_done.emit(job.reply_id, job.result)
            if self._queue.empty():
                self._set_busy(False)
        self._set_busy(False)
        # Runs before the thread's event loop starts; the posted quit ends it right away.
        QTimer.singleShot(0, self._thread.quit)

    def _set_busy(self, value: bool) -> None:
        if value != self._busy:
            self._busy = value
            self.busy_changed.emit(value)

    def _report_model(self) -> None:
        if self.engine is None:
            return
        model = self.engine.loaded_model or ""
        if model != self._model or not self._device:
            self._model = model
            try:
                self._device = self.engine.device_info()
            except Exception:  # noqa: BLE001
                self._device = "unknown"
            self.model_changed.emit(self._model, self._device)

    def _engine(self) -> Any:
        if self.engine is None:
            from ..engine import get_engine

            self.engine = get_engine(self.project, fake=self.fake)
        return self.engine

    def _on_event(self, e: dict[str, Any]) -> None:
        if e.get("type") == "progress":
            self.progress.emit(int(e["done"]), int(e["total"]))
        if e.get("type") == "done" and "summary" in e:
            e = {**e, "summary": asdict(e["summary"])}
        self.event.emit(e)
        self._report_model()

    def _run(self, job: Job) -> dict[str, Any]:
        from ..bake import Baker

        p = job.payload
        if job.kind == "bake":
            from ..ledger import Ledger
            from ..lines_io import load_lines
            from ..planner import plan
            from ..schema import load_voices
            from ..tones import load_project_tones

            project = self.project
            the_plan = plan(
                project,
                load_voices(project.paths.voices),
                load_lines(project),
                load_project_tones(project),
                Ledger.for_root(project.root),
                only_lines=p.get("only_lines"),
                force=bool(p.get("force", False)),
                force_refs=bool(p.get("force_refs", False)),
            )
            self.progress.emit(0, len(the_plan.jobs))
            if the_plan.is_empty():
                self.event.emit({"type": "info", "msg": "Nothing to bake: every line is current."})
            baker = Baker(self._engine(), project, self._on_event)
            summary = baker.run(the_plan, cancel=self._cancel.is_set)
            return {"ok": True, "summary": asdict(summary)}
        if job.kind == "regenerate":
            baker = Baker(self._engine(), self.project, self._on_event)
            res = baker.regenerate(str(p["line_id"]), p.get("seed"))
            out = asdict(res)
            out["ok"] = res.ok
            return out
        # candidates
        from ..refs import gen_candidates

        paths = gen_candidates(
            self._engine(), self.project, str(p["voice"]), str(p["tone"]), int(p.get("n", 4))
        )
        return {
            "ok": True,
            "voice": p["voice"],
            "tone": p["tone"],
            "paths": [str(x) for x in paths],
        }
