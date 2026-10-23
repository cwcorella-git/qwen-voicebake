"""Decide what a bake has to do: which references and which takes, by which route."""

from __future__ import annotations

import fnmatch
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .hashing import sha1_file, take_inputs_hash
from .ledger import Ledger, take_rel
from .refs import load_lock, ref_path, ref_status

if TYPE_CHECKING:
    from .config import Project
    from .schema import Line, Voice

USABLE_REF = ("ok", "pinned", "pinned-stale")


def route_for(line: Line) -> str:
    return "design" if line.kind == "vocal" or line.direction else "clone"


@dataclass
class Job:
    line: Line
    voice: Voice
    tone_text: str
    route: str
    rel: str  # take path relative to the output dir
    max_new_tokens: int
    state: str  # ledger state at plan time


@dataclass
class Plan:
    ref_pairs: list[tuple[str, str]] = field(default_factory=list)
    design_jobs: list[Job] = field(default_factory=list)
    clone_jobs: list[Job] = field(default_factory=list)
    skipped_human: list[str] = field(default_factory=list)
    up_to_date: list[str] = field(default_factory=list)
    force: bool = False
    force_refs: bool = False
    voices: dict[str, Voice] = field(default_factory=dict)
    lines: list[Line] = field(default_factory=list)
    tones: dict[str, str] = field(default_factory=dict)

    @property
    def jobs(self) -> list[Job]:
        return self.design_jobs + self.clone_jobs

    def is_empty(self) -> bool:
        return not self.design_jobs and not self.clone_jobs


def _matches(line_id: str, globs: Iterable[str] | None) -> bool:
    if not globs:
        return True
    return any(fnmatch.fnmatchcase(line_id, g) for g in globs)


def expected_take_hash(
    project: Project, line: Line, voice: Voice, tone_text: str, route: str
) -> str | None:
    """Hash the take would have now, or None if its reference does not exist yet."""
    ref_sha = None
    if route == "clone":
        rp = ref_path(project, voice.name, line.tone)
        if not rp.is_file():
            return None
        ref_sha = sha1_file(rp)
    return take_inputs_hash(line, voice, tone_text, route, ref_sha, project.engine, project.paths)


def plan(
    project: Project,
    voices: dict[str, Voice],
    lines: list[Line],
    tones: dict[str, str],
    ledger: Ledger,
    only_voices: Iterable[str] | None = None,
    only_lines: Iterable[str] | None = None,
    force: bool = False,
    force_refs: bool = False,
) -> Plan:
    only_v = set(only_voices) if only_voices else None
    globs = list(only_lines) if only_lines else None
    fmt = project.paths.format
    lock = load_lock(project)
    ref_state: dict[tuple[str, str], str] = {}
    p = Plan(force=force, force_refs=force_refs, voices=voices, lines=lines, tones=tones)

    for line in lines:
        if only_v is not None and line.voice not in only_v:
            continue
        if not _matches(line.id, globs):
            continue
        voice = voices[line.voice]
        tone_text = tones[line.tone]
        route = route_for(line)
        pair = (line.voice, line.tone)
        if route == "clone" and pair not in ref_state:
            ref_state[pair] = ref_status(project, voice, line.tone, tone_text, lock)

        h = None
        if route == "design" or ref_state[pair] in USABLE_REF:
            h = expected_take_hash(project, line, voice, tone_text, route)
        state = ledger.line_state(line, project.paths.out, h, fmt)
        if state == "human":
            p.skipped_human.append(line.id)
            continue

        ref_needs_work = route == "clone" and (
            ref_state[pair] not in USABLE_REF or (force_refs and ref_state[pair] == "ok")
        )
        if state == "ok" and not force and not ref_needs_work:
            p.up_to_date.append(line.id)
            continue

        max_tokens = (
            project.engine.vocal_max_new_tokens
            if line.kind == "vocal"
            else project.engine.max_new_tokens
        )
        job = Job(line, voice, tone_text, route, take_rel(line, fmt), max_tokens, state)
        if route == "design":
            p.design_jobs.append(job)
        else:
            p.clone_jobs.append(job)
            if pair not in p.ref_pairs:
                p.ref_pairs.append(pair)
    return p
