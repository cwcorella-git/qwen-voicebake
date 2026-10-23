"""Reference clips: one designed clip per (voice, tone), used as the clone prompt."""

from __future__ import annotations

import json
import shutil
import time
from collections.abc import Callable, Iterable
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ._atomic import atomic_write, atomic_write_text
from .hashing import ref_inputs_hash, sha1_file
from .post import EmptyAudioError, postprocess, write_audio
from .qa import qa_check
from .tones import instruct_for

if TYPE_CHECKING:
    from .config import Project
    from .engine.base import Engine
    from .schema import Voice

REF_FORMAT = "ogg"
LOCK_NAME = "refs.lock.json"

Event = Callable[[dict[str, Any]], None]


def _noop(_: dict[str, Any]) -> None:
    pass


def ref_key(voice: str, tone: str) -> str:
    return f"{voice}/{tone}"


def ref_path(project: Project, voice: str, tone: str) -> Path:
    return project.paths.refs / voice / f"{tone}.{REF_FORMAT}"


def candidate_dir(project: Project, voice: str, tone: str) -> Path:
    return project.state_dir / "candidates" / voice / tone


def candidate_path(project: Project, voice: str, tone: str, seed: int) -> Path:
    return candidate_dir(project, voice, tone) / f"seed{seed}.{REF_FORMAT}"


def load_lock(project: Project) -> dict[str, dict[str, Any]]:
    p = project.paths.refs / LOCK_NAME
    if not p.is_file():
        return {}
    with open(p, encoding="utf-8") as f:
        return dict(json.load(f))


def save_lock(project: Project, lock: dict[str, dict[str, Any]]) -> None:
    text = json.dumps(lock, indent=2, sort_keys=True)
    atomic_write_text(project.paths.refs / LOCK_NAME, text + "\n")


def _expected_hash(project: Project, voice: Voice, tone: str, tone_text: str, seed: int) -> str:
    return ref_inputs_hash(replace(voice, seed=seed), tone, tone_text, project.engine)


def ref_status(
    project: Project,
    voice: Voice,
    tone: str,
    tone_text: str,
    lock: dict[str, dict[str, Any]] | None = None,
) -> str:
    """Return "missing", "modified", "ok", "stale", "pinned" or "pinned-stale".

    "modified" means the file on disk differs from the one recorded in the lock (replaced by
    hand); it is used as-is and only regenerated with force.

    A pinned reference is compared using the seed it was made with, so picking a candidate
    with a different seed does not by itself make it stale.
    """
    lock = load_lock(project) if lock is None else lock
    entry = lock.get(ref_key(voice.name, tone))
    if entry is None or not ref_path(project, voice.name, tone).is_file():
        return "missing"
    if entry.get("audio_sha1") and entry["audio_sha1"] != sha1_file(
        ref_path(project, voice.name, tone)
    ):
        return "modified"
    if entry.get("pinned"):
        seed = int(entry.get("seed", voice.seed))
        current = entry.get("inputs_hash") == _expected_hash(project, voice, tone, tone_text, seed)
        return "pinned" if current else "pinned-stale"
    current = entry.get("inputs_hash") == _expected_hash(
        project, voice, tone, tone_text, voice.seed
    )
    return "ok" if current else "stale"


def _design_ref(engine: Engine, project: Project, voice: Voice, tone_text: str, seed: int):
    temp = voice.temperature if voice.temperature is not None else project.engine.temperature
    res = engine.design(
        voice.ref_text,
        instruct_for(voice, tone_text),
        voice.language or project.engine.language,
        seed,
        temp,
        project.engine.max_new_tokens,
    )
    return res, postprocess(res.wav, res.sr, False)


def _record(
    project: Project,
    lock: dict[str, dict[str, Any]],
    voice: Voice,
    tone: str,
    tone_text: str,
    seed: int,
    pinned: bool,
) -> None:
    path = ref_path(project, voice.name, tone)
    lock[ref_key(voice.name, tone)] = {
        "file": path.relative_to(project.paths.refs).as_posix(),
        "inputs_hash": _expected_hash(project, voice, tone, tone_text, seed),
        "audio_sha1": sha1_file(path),
        "seed": seed,
        "pinned": pinned,
        "model": project.engine.design_model,
        "created": time.time(),
    }


def ensure_refs(
    engine: Engine,
    project: Project,
    pairs: Iterable[tuple[str, str]],
    force: bool = False,
    on_event: Event = _noop,
    voices: dict[str, Voice] | None = None,
    tones: dict[str, str] | None = None,
    failed: list[tuple[str, str]] | None = None,
) -> list[tuple[str, str]]:
    """Design references that are missing or stale (all unpinned ones when force).

    Pinned references are never regenerated; a pinned-stale one only emits a warning.
    A reference that fails (engine error, empty or hard-QA audio) emits a warning, is appended
    to failed (when given) and does not stop the others. Hard-QA audio goes to
    .voicebake/rejected/refs/. Returns the pairs that were (re)designed.
    """
    voices, tones = _voices_tones(project, voices, tones)
    lock = load_lock(project)
    made: list[tuple[str, str]] = []
    for vname, tone in dict.fromkeys(pairs):
        voice = voices[vname]
        tone_text = tones[tone]
        status = ref_status(project, voice, tone, tone_text, lock)
        if status == "pinned-stale":
            on_event(
                {
                    "type": "warn",
                    "route": "design",
                    "voice": vname,
                    "tone": tone,
                    "msg": "pinned reference is stale; unpin it to regenerate",
                }
            )
            continue
        if status == "pinned" or (status in ("ok", "modified") and not force):
            continue
        had_file = ref_path(project, vname, tone).is_file()
        try:
            res, wav = _design_ref(engine, project, voice, tone_text, voice.seed)
            qa = qa_check(wav, res.sr, voice.ref_text, "speech", project.qa)
            if qa.level == "hard":
                try:
                    rej = project.state_dir / "rejected" / "refs" / vname / f"{tone}.{REF_FORMAT}"
                    write_audio(rej, wav, res.sr, REF_FORMAT)
                except EmptyAudioError:
                    pass
                raise RuntimeError("rejected: " + ", ".join(qa.reasons))
            write_audio(ref_path(project, vname, tone), wav, res.sr, REF_FORMAT)
        except Exception as e:  # noqa: BLE001 - one bad reference must not stop the bake
            if had_file:
                # The previous reference file is untouched; keep cloning from it.
                on_event(
                    {
                        "type": "warn",
                        "route": "design",
                        "voice": vname,
                        "tone": tone,
                        "failed": False,
                        "msg": "reference regeneration failed, kept previous reference: "
                        f"{type(e).__name__}: {e}",
                    }
                )
                continue
            if failed is not None:
                failed.append((vname, tone))
            on_event(
                {
                    "type": "warn",
                    "route": "design",
                    "voice": vname,
                    "tone": tone,
                    "failed": True,
                    "msg": f"reference failed: {type(e).__name__}: {e}",
                }
            )
            continue
        _record(project, lock, voice, tone, tone_text, voice.seed, pinned=False)
        save_lock(project, lock)
        made.append((vname, tone))
        on_event(
            {
                "type": "ref",
                "route": "design",
                "voice": vname,
                "tone": tone,
                "status": status,
                "duration": len(wav) / res.sr,
            }
        )
    return made


def gen_candidates(
    engine: Engine,
    project: Project,
    voice: str,
    tone: str,
    n: int = 4,
    seeds: list[int] | None = None,
    voices: dict[str, Voice] | None = None,
    tones: dict[str, str] | None = None,
) -> list[Path]:
    """Design n candidate references with different seeds (default voice.seed + 0..n-1)."""
    voices, tones = _voices_tones(project, voices, tones)
    v = voices[voice]
    seeds = list(seeds) if seeds else [v.seed + i for i in range(n)]
    out: list[Path] = []
    for seed in seeds:
        res, wav = _design_ref(engine, project, v, tones[tone], seed)
        path = candidate_path(project, voice, tone, seed)
        write_audio(path, wav, res.sr, REF_FORMAT)
        out.append(path)
    return out


def pick_candidate(
    project: Project,
    voice: str,
    tone: str,
    seed: int,
    voices: dict[str, Voice] | None = None,
    tones: dict[str, str] | None = None,
) -> Path:
    """Copy a candidate over the reference, pin it and record its seed."""
    voices, tones = _voices_tones(project, voices, tones)
    src = candidate_path(project, voice, tone, seed)
    if not src.is_file():
        raise FileNotFoundError(f"no candidate {src}")
    dst = ref_path(project, voice, tone)
    atomic_write(dst, lambda tmp: shutil.copyfile(src, tmp))
    lock = load_lock(project)
    _record(project, lock, voices[voice], tone, tones[tone], seed, pinned=True)
    save_lock(project, lock)
    return dst


def set_pinned(project: Project, voice: str, tone: str, pinned: bool) -> None:
    lock = load_lock(project)
    key = ref_key(voice, tone)
    if key not in lock:
        raise KeyError(f"no reference for {key}")
    lock[key]["pinned"] = bool(pinned)
    save_lock(project, lock)


def _voices_tones(
    project: Project, voices: dict[str, Voice] | None, tones: dict[str, str] | None
) -> tuple[dict[str, Voice], dict[str, str]]:
    if voices is None:
        from .schema import load_voices

        voices = load_voices(project.paths.voices)
    if tones is None:
        from .tones import load_project_tones

        tones = load_project_tones(project)
    return voices, tones
