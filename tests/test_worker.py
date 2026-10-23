import pytest

pytest.importorskip("PySide6")

from qwen_voicebake.app.worker import EngineWorker  # noqa: E402


class _Project:
    pass


def test_call_timeout_cancels_queued_job():
    w = EngineWorker(_Project())  # type: ignore[arg-type]
    res = w.call("regenerate", {"line_id": "x"}, timeout=0.05)
    assert res["ok"] is False and "cancelled" in res["error"]
    job = w._queue.get_nowait()
    assert job.cancelled and not job.started


def test_call_timeout_on_running_job_reports_may_finish(monkeypatch):
    w = EngineWorker(_Project())  # type: ignore[arg-type]
    real = w._enqueue

    def enqueue(kind, payload):
        job = real(kind, payload)
        job.started = True  # as if the worker thread had picked it up
        return job

    monkeypatch.setattr(w, "_enqueue", enqueue)
    res = w.call("regenerate", {"line_id": "x"}, timeout=0.05)
    assert res == {
        "ok": False,
        "error": "timed out; the line may still finish and appear in the manifest",
    }
    assert not w._queue.get_nowait().cancelled
