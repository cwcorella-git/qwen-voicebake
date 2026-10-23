"""Quality checks on generated takes (no torch)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from .config import QACfg


@dataclass
class QAResult:
    level: str  # "ok", "soft" or "hard"
    reasons: list[str] = field(default_factory=list)
    duration: float = 0.0


def qa_check(
    wav_or_path: np.ndarray | str | os.PathLike[str],
    sr: int,
    text: str,
    kind: str,
    qa_cfg: QACfg,
) -> QAResult:
    """Check duration against limits. For a path, the file's own sample rate is used."""
    if isinstance(wav_or_path, (str, os.PathLike)):
        import soundfile as sf

        info = sf.info(wav_or_path)
        duration = info.frames / info.samplerate
    else:
        duration = len(wav_or_path) / sr if sr else 0.0

    hard: list[str] = []
    soft: list[str] = []
    if duration > qa_cfg.max_seconds:
        hard.append("runaway")
    if duration < qa_cfg.min_seconds:
        hard.append("empty")
    if not hard and kind == "speech":
        words = len(text.split())
        if words >= 2:
            low, high = qa_cfg.sec_per_word
            spw = duration / words
            if spw < low:
                soft.append(f"too fast ({spw:.2f} s/word)")
            elif spw > high:
                soft.append(f"too slow ({spw:.2f} s/word)")
        elif words == 1 and duration > qa_cfg.one_word_max:
            soft.append(f"long for one word ({duration:.1f} s)")
    if hard:
        return QAResult("hard", hard + soft, duration)
    if soft:
        return QAResult("soft", soft, duration)
    return QAResult("ok", [], duration)
