"""Stable input hashes used to decide whether a take or reference is current."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

from .tones import instruct_for

if TYPE_CHECKING:
    from .config import EngineCfg, PathsCfg
    from .schema import Line, Voice


def stable_hash(obj: Any) -> str:
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def sha1_file(path: Any) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _temperature(voice: Voice, engine_cfg: EngineCfg) -> float:
    return voice.temperature if voice.temperature is not None else engine_cfg.temperature


def _language(voice: Voice, engine_cfg: EngineCfg) -> str:
    return voice.language or engine_cfg.language


def ref_inputs_hash(voice: Voice, tone_name: str, tone_text: str, engine_cfg: EngineCfg) -> str:
    """Hash of everything that determines a reference clip for (voice, tone)."""
    return stable_hash(
        {
            "kind": "ref",
            "voice": voice.name,
            "tone": tone_name,
            "text": voice.ref_text,
            "instruct": instruct_for(voice, tone_text),
            "design_model": engine_cfg.design_model,
            "seed": voice.seed,
            "temperature": _temperature(voice, engine_cfg),
            "language": _language(voice, engine_cfg),
            "max_new_tokens": engine_cfg.max_new_tokens,
        }
    )


def take_inputs_hash(
    line: Line,
    voice: Voice,
    tone_text: str,
    route: str,
    ref_audio_sha1: str | None,
    engine_cfg: EngineCfg,
    paths_cfg: PathsCfg,
) -> str:
    """Hash of everything that determines a line's take. route is 'design' or 'clone'."""
    common = {
        "route": route,
        "text": line.text,
        "language": _language(voice, engine_cfg),
        "temperature": _temperature(voice, engine_cfg),
        "format": paths_cfg.format,
        "normalize": paths_cfg.normalize,
    }
    if route == "clone":
        common.update(
            {
                "instruct": voice.instruct,
                "tone_text": tone_text,
                "ref_audio_sha1": ref_audio_sha1,
                "clone_model": engine_cfg.clone_model,
            }
        )
    elif route == "design":
        max_tokens = (
            engine_cfg.vocal_max_new_tokens if line.kind == "vocal" else engine_cfg.max_new_tokens
        )
        common.update(
            {
                "instruct": instruct_for(voice, tone_text, line.direction),
                "design_model": engine_cfg.design_model,
                "seed": voice.seed,
                "max_new_tokens": max_tokens,
            }
        )
    else:
        raise ValueError(f"unknown route '{route}'")
    return stable_hash(common)
