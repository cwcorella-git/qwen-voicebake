"""Run a plan: design references and takes first, then clone takes, then write the manifest."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .hashing import sha1_file
from .ledger import HUMAN_SUFFIX, Ledger, take_rel
from .manifest import write_manifest
from .planner import Job, Plan, expected_take_hash, route_for
from .post import EmptyAudioError, postprocess, write_audio
from .qa import qa_check
from .refs import ensure_refs, ref_path
from .schema import ID_RE

if TYPE_CHECKING:
    from .config import Project
    from .engine.base import AudioResult, Engine
    from .schema import Line

Event = Callable[[dict[str, Any]], None]


def _noop(_: dict[str, Any]) -> None:
    pass


@dataclass
class TakeResult:
    line_id: str
    route: str
    ok: bool
    qa: str = ""
    reasons: list[str] = field(default_factory=list)
    duration: float = 0.0
    rel: str = ""
    path: str = ""
    error: str = ""


@dataclass
class BakeSummary:
    baked: list[str] = field(default_factory=list)
    soft: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    up_to_date: list[str] = field(default_factory=list)
    skipped_human: list[str] = field(default_factory=list)
    refs_made: list[tuple[str, str]] = field(default_factory=list)
    planned: int = 0
    cancelled: bool = False
    dry_run: bool = False
    seconds: float = 0.0


class Baker:
    def __init__(self, engine: Engine | None, project: Project, on_event: Event = _noop) -> None:
        self.engine = engine
        self.project = project
        self.on_event = on_event
        self._prompts: dict[tuple[str, str], Any] = {}
        self._prompts_model: str | None = None

    @property
    def rejected_dir(self) -> Path:
        return self.project.state_dir / "rejected"

    def unsafe_reason(self, line: Line) -> str | None:
        """Why a line must not be written, or None. Guards against ids or voice names that
        would put files outside the output folder (for example "..")."""
        if not ID_RE.match(line.id) or not ID_RE.match(line.voice) or not ID_RE.match(line.tone):
            return "invalid id, voice or tone name"
        out_dir = self.project.paths.out.resolve()
        target = (out_dir / take_rel(line, self.project.paths.format)).resolve()
        if not target.is_relative_to(out_dir) or target.parent == out_dir:
            return "output path is outside the output folder"
        if route_for(line) == "clone":
            refs_dir = self.project.paths.refs.resolve()
            ref = ref_path(self.project, line.voice, line.tone).resolve()
            if not ref.is_relative_to(refs_dir) or ref.parent == refs_dir:
                return "reference path is outside the references folder"
        return None

    # -- one take ---------------------------------------------------------------

    def _temperature(self, job: Job) -> float:
        t = job.voice.temperature
        return t if t is not None else self.project.engine.temperature

    def _language(self, job: Job) -> str:
        return job.voice.language or self.project.engine.language

    def _clone_prompt(self, job: Job) -> Any:
        import soundfile as sf

        rp = ref_path(self.project, job.voice.name, job.line.tone)
        key = (self.project.engine.clone_model, sha1_file(rp))
        assert self.engine is not None
        # Prompts belong to a loaded model instance: drop them if the engine moved to another
        # model since they were made, then make sure the clone model is loaded.
        if self.engine.loaded_model != self._prompts_model:
            self._prompts.clear()
        self.engine.load(getattr(self.engine, "clone_model", self.project.engine.clone_model))
        if key not in self._prompts:
            wav, sr = sf.read(str(rp), dtype="float32", always_2d=False)
            if wav.ndim > 1:
                wav = wav.mean(axis=1)
            assert self.engine is not None
            self._prompts[key] = self.engine.make_clone_prompt(wav, sr, job.voice.ref_text)
            self._prompts_model = self.engine.loaded_model
        return self._prompts[key]

    def _synth(self, job: Job, seed: int) -> AudioResult:
        assert self.engine is not None
        if job.route == "design":
            from .tones import instruct_for

            return self.engine.design(
                job.line.text,
                instruct_for(job.voice, job.tone_text, job.line.direction),
                self._language(job),
                seed,
                self._temperature(job),
                job.max_new_tokens,
            )
        return self.engine.clone(
            job.line.text,
            self._language(job),
            self._clone_prompt(job),
            seed,
            self._temperature(job),
            job.max_new_tokens,
        )

    def _take(self, job: Job, ledger: Ledger, h: str, seed: int | None = None) -> TakeResult:
        out_path = self.project.paths.out / job.rel
        fmt = self.project.paths.format
        res = TakeResult(job.line.id, job.route, ok=False, rel=job.rel, path=str(out_path))
        try:
            audio = self._synth(job, job.voice.seed if seed is None else seed)
            wav = postprocess(audio.wav, audio.sr, self.project.paths.normalize)
            qa = qa_check(wav, audio.sr, job.line.text, job.line.kind, self.project.qa)
        except Exception as e:  # noqa: BLE001 - one bad line must not stop the bake
            res.error = f"{type(e).__name__}: {e}"
            ledger.mark_failed(job.rel, res.error)
            return res
        res.qa, res.reasons, res.duration = qa.level, qa.reasons, qa.duration
        if qa.level == "hard":
            ledger.mark_failed(job.rel, ", ".join(qa.reasons))
            res.error = "rejected: " + ", ".join(qa.reasons)
            try:
                write_audio(self.rejected_dir / job.rel, wav, audio.sr, fmt)
            except EmptyAudioError:
                pass
            return res
        try:
            write_audio(out_path, wav, audio.sr, fmt)
        except EmptyAudioError as e:
            res.error = str(e)
            ledger.mark_failed(job.rel, res.error)
            return res
        ledger.stamp(job.rel, h, job.route, qa.duration, qa.level, qa.reasons, seed=seed)
        res.ok = True
        return res

    def _emit_take(self, res: TakeResult, index: int, total: int) -> None:
        self.on_event(
            {
                "type": "take",
                "route": res.route,
                "line_id": res.line_id,
                "ok": res.ok,
                "qa": res.qa,
                "reasons": res.reasons,
                "duration": res.duration,
                "path": res.path,
                "rel": res.rel,
                "error": res.error,
            }
        )
        self.on_event({"type": "progress", "route": res.route, "done": index, "total": total})

    # -- whole plan ---------------------------------------------------------------

    def run(
        self,
        plan: Plan,
        dry_run: bool = False,
        limit: int | None = None,
        cancel: Callable[[], bool] = lambda: False,
    ) -> BakeSummary:
        t0 = time.monotonic()
        jobs = plan.design_jobs + plan.clone_jobs
        if limit is not None:
            jobs = jobs[:limit]
        s = BakeSummary(
            up_to_date=list(plan.up_to_date),
            skipped_human=list(plan.skipped_human),
            planned=len(jobs),
            dry_run=dry_run,
        )
        if dry_run:
            for job in jobs:
                self.on_event(
                    {"type": "plan", "route": job.route, "line_id": job.line.id, "state": job.state}
                )
            self.on_event({"type": "done", "route": "", "summary": s})
            return s
        if self.engine is None:
            raise ValueError("an engine is needed unless dry_run is set")

        ledger = Ledger.for_root(self.project.root)
        unsafe = {j.line.id: r for j in jobs if (r := self.unsafe_reason(j.line))}
        design = [j for j in jobs if j.route == "design"]
        clone = [j for j in jobs if j.route == "clone"]
        safe_clone = [j for j in clone if j.line.id not in unsafe]
        pairs = [
            p for p in plan.ref_pairs if any((j.voice.name, j.line.tone) == p for j in safe_clone)
        ]
        total = len(jobs)
        done = 0
        failed_refs: list[tuple[str, str]] = []
        try:
            # Design model: references, then design takes.
            if pairs and not cancel():
                s.refs_made = ensure_refs(
                    self.engine,
                    self.project,
                    pairs,
                    force=plan.force_refs,
                    on_event=self.on_event,
                    voices=plan.voices,
                    tones=plan.tones,
                    failed=failed_refs,
                )
            for job in design + clone:
                if cancel():
                    s.cancelled = True
                    break
                done += 1
                if job.line.id in unsafe:
                    res = TakeResult(job.line.id, job.route, False, error=unsafe[job.line.id])
                    s.failed.append(job.line.id)
                    self._emit_take(res, done, total)
                    continue
                h = expected_take_hash(self.project, job.line, job.voice, job.tone_text, job.route)
                if job.route == "clone" and (job.voice.name, job.line.tone) in failed_refs:
                    h = None
                if h is None:
                    ledger.mark_failed(job.rel, "reference missing")
                    res = TakeResult(job.line.id, job.route, False, error="reference missing")
                    s.failed.append(job.line.id)
                    self._emit_take(res, done, total)
                    continue
                out_file = self.project.paths.out / job.rel
                if not plan.force and out_file.is_file() and ledger.is_current(job.rel, h):
                    s.up_to_date.append(job.line.id)
                    continue
                res = self._take(job, ledger, h)
                ledger.save()
                (s.baked if res.ok else s.failed).append(job.line.id)
                if res.ok and res.qa == "soft":
                    s.soft.append(job.line.id)
                self._emit_take(res, done, total)
        finally:
            ledger.save()
            write_manifest(self.project, plan.voices, plan.lines, ledger)
        s.seconds = time.monotonic() - t0
        self.on_event({"type": "done", "route": "", "summary": s})
        return s

    # -- single line ------------------------------------------------------------

    def regenerate(self, line_id: str, seed: int | None = None) -> TakeResult:
        """Re-synthesize one line (ensuring its reference) and stamp it as current."""
        from .lines_io import load_lines
        from .schema import load_voices
        from .tones import load_project_tones

        if self.engine is None:
            raise ValueError("an engine is needed to regenerate")
        voices = load_voices(self.project.paths.voices)
        lines = load_lines(self.project)
        tones = load_project_tones(self.project)
        line = next((ln for ln in lines if ln.id == line_id), None)
        if line is None:
            raise KeyError(f"unknown line '{line_id}'")
        route = route_for(line)
        reason = self.unsafe_reason(line)
        if reason is not None:
            res = TakeResult(line.id, route, False, error=reason)
            self._emit_take(res, 1, 1)
            return res
        voice = voices[line.voice]
        fmt = self.project.paths.format
        max_tokens = (
            self.project.engine.vocal_max_new_tokens
            if line.kind == "vocal"
            else self.project.engine.max_new_tokens
        )
        job = Job(line, voice, tones[line.tone], route, take_rel(line, fmt), max_tokens, "")
        out_file = self.project.paths.out / job.rel
        if Path(str(out_file) + HUMAN_SUFFIX).exists():
            res = TakeResult(
                line.id,
                route,
                False,
                rel=job.rel,
                path=str(out_file),
                error="line is marked as a human take; remove the .human marker to regenerate",
            )
            self._emit_take(res, 1, 1)
            return res
        ledger = Ledger.for_root(self.project.root)
        failed_refs: list[tuple[str, str]] = []
        if route == "clone":
            ensure_refs(
                self.engine,
                self.project,
                [(line.voice, line.tone)],
                on_event=self.on_event,
                voices=voices,
                tones=tones,
                failed=failed_refs,
            )
        h = expected_take_hash(self.project, line, voice, job.tone_text, route)
        if h is None or failed_refs:
            res = TakeResult(line.id, route, False, error="reference missing")
        else:
            res = self._take(job, ledger, h, seed=seed)
        ledger.save()
        write_manifest(self.project, voices, lines, ledger)
        self._emit_take(res, 1, 1)
        return res
