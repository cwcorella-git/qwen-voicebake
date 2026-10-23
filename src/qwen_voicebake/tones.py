"""Tone texts appended to a voice description to steer delivery."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from .schema import Voice

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

if TYPE_CHECKING:
    from .config import Project

BUILTIN_TONES: dict[str, str] = {
    "neutral": "",
    "seeking": " Right now: searching and tentative, thinking aloud, reaching for understanding.",
    "trust": " Right now: warm and confiding, open, quietly trusting.",
    "guilt": " Right now: quiet remorse, heavy and sincere, voice lowered.",
    "fear": " Right now: tense and afraid, breath tight, quick and low.",
    "anger": " Right now: hard and clipped, controlled anger pushing through.",
    "empathy": " Right now: gentle and understanding, softened, caring.",
    "assertion": " Right now: firm and certain, planting each word, no hedging.",
    "cold": " Right now: cold, final, dismissive, barely contained anger, clipped short.",
    "opposition": " Right now: pushing back, resistant, edged with defiance.",
    "curiosity": " Right now: curious and alert, a lift of genuine interest.",
    "warm": " Right now: warm and open, a little softer, welcoming.",
    "disgust": " Right now: recoiling, distaste in the voice, clipped.",
    "elation": " Right now: bright and buoyant, energy lifting the delivery.",
    "suffering": " Right now: worn and pained, heavy, effortful.",
    "whisper": " Right now: whispering, breathy and close, barely voiced.",
    "shout": (" Right now: shouting across a distance, loud and projected, strained at the top."),
    "murmur": " Right now: murmuring low to themselves, soft and indistinct at the edges.",
    "singsong": " Right now: sing-song and playful, pitch bouncing up and down.",
    "monotone": " Right now: flat monotone, no pitch movement, emotionally absent.",
    "fast": " Right now: talking quickly, words tumbling out, barely pausing.",
    "slow": " Right now: slow and deliberate, long pauses between phrases.",
    "sad": " Right now: sad and subdued, voice heavy, close to tears but holding.",
    "joy": " Right now: happy and light, smiling through the words.",
    "amused": " Right now: amused, a laugh just under the surface.",
    "sarcastic": " Right now: dry and sarcastic, meaning the opposite of the words.",
    "nervous": " Right now: nervous and unsure, hesitating, voice slightly shaky.",
    "panicked": " Right now: panicked, breathless and rushed, pitch rising.",
    "pleading": " Right now: pleading, desperate and earnest, voice cracking.",
    "proud": " Right now: proud and pleased with themselves, chest out, unhurried.",
    "bored": " Right now: bored and uninterested, dragging the words out.",
    "tired": " Right now: exhausted, low energy, words sagging at the ends.",
    "awe": " Right now: in awe, hushed and wondering, slowed by amazement.",
    "relief": " Right now: relieved, tension draining out, a long exhale in the voice.",
    "contempt": " Right now: contemptuous, looking down on the listener, sneering.",
    "shy": " Right now: shy and quiet, trailing off, avoiding attention.",
    "injured": " Right now: hurt and in pain, words forced out between sharp breaths.",
    "breathless": " Right now: out of breath after running, gasping between phrases.",
    "slurred": " Right now: drunk, words slurring together, loose and unsteady.",
    "sick": " Right now: sick and congested, weak and hoarse.",
    "shivering": " Right now: freezing cold, teeth chattering, voice trembling.",
    "crying": " Right now: crying, voice breaking and wet, catching on sobs.",
    "laughing": " Right now: laughing while talking, words bubbling through laughter.",
    "radio": " Right now: speaking over a radio, clipped and procedural, brief and clear.",
    "announcer": " Right now: making a public announcement, even, clear and measured.",
    "storyteller": (
        " Right now: telling a story, unhurried and expressive, drawing the listener in."
    ),
    "commanding": " Right now: giving orders, loud, sharp and authoritative.",
    "tender": " Right now: tender and intimate, very soft, speaking to someone close.",
}


def load_project_tones(project: Project) -> dict[str, str]:
    """Built-in tones plus the project's tones.toml [tones] table (adds and overrides)."""
    tones = dict(BUILTIN_TONES)
    path = project.paths.tones
    if path.is_file():
        with open(path, "rb") as f:
            data = tomllib.load(f)
        for name, text in data.get("tones", {}).items():
            if not isinstance(text, str):
                raise ValueError(f"tones.toml: tone '{name}' must be a string")
            # Stored texts follow the built-in convention: a leading space unless empty.
            tones[name] = (" " + text.strip()) if text.strip() else ""
    return tones


def instruct_for(voice: Voice, tone_text: str, direction: str = "") -> str:
    """Full instruction: voice description + tone text + optional per-line direction."""
    out = voice.instruct + tone_text
    if direction:
        out += " " + direction
    return out
