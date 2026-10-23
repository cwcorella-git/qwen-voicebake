"""Post-processing and writing of generated audio."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np

from ._atomic import atomic_write

TRIM_THRESHOLD = 0.01
TRIM_PAD_SECONDS = 0.03
DEFAULT_LUFS = -18.0
MIN_WRITE_SECONDS = 0.05


class EmptyAudioError(ValueError):
    """Raised when audio is too short to write safely."""


def postprocess(wav: np.ndarray, sr: int, normalize: bool | float = False) -> np.ndarray:
    """Clean, trim and optionally loudness-normalize a mono float waveform."""
    wav = np.nan_to_num(np.asarray(wav, dtype=np.float32), nan=0.0, posinf=0.0, neginf=0.0)
    wav = np.clip(wav, -1.0, 1.0)
    if wav.size:
        loud = np.nonzero(np.abs(wav) > TRIM_THRESHOLD)[0]
        if loud.size:
            pad = int(TRIM_PAD_SECONDS * sr)
            start = max(0, int(loud[0]) - pad)
            end = min(wav.size, int(loud[-1]) + 1 + pad)
            wav = wav[start:end]
        else:
            wav = wav[:0]
    if normalize is not False and normalize is not None and wav.size:
        target = DEFAULT_LUFS if normalize is True else float(normalize)
        wav = _normalize_loudness(wav, sr, target)
    return np.ascontiguousarray(wav, dtype=np.float32)


def _normalize_loudness(wav: np.ndarray, sr: int, target: float) -> np.ndarray:
    import pyloudnorm  # lazy: optional [loudness] extra

    meter = pyloudnorm.Meter(sr)
    if wav.size < int(0.4 * sr):  # BS.1770 needs a 400 ms block; pad a copy for measuring
        measured = np.pad(wav, (0, int(0.4 * sr) - wav.size))
    else:
        measured = wav
    loudness = meter.integrated_loudness(measured)
    if not np.isfinite(loudness):
        return wav
    out = wav * np.float32(10 ** ((target - loudness) / 20.0))
    return np.clip(out, -1.0, 1.0).astype(np.float32)


WRITE_BLOCK_FRAMES = 4096


def write_audio(path: str | os.PathLike[str], wav: np.ndarray, sr: int, fmt: str) -> None:
    """Atomically write wav as ogg (Vorbis) or wav (PCM_16)."""
    import soundfile as sf

    if fmt not in ("ogg", "wav"):
        raise ValueError(f"unsupported format '{fmt}'")
    wav = np.ascontiguousarray(wav, dtype=np.float32)
    if wav.size < MIN_WRITE_SECONDS * sr:
        raise EmptyAudioError(f"audio too short to write ({wav.size} samples at {sr} Hz)")
    container, subtype = ("OGG", "VORBIS") if fmt == "ogg" else ("WAV", "PCM_16")

    def _w(tmp: str) -> None:
        # Write in blocks: one large Vorbis write overflows the stack on Windows libsndfile.
        channels = 1 if wav.ndim == 1 else wav.shape[1]
        with sf.SoundFile(tmp, "w", sr, channels, subtype, format=container) as f:
            for i in range(0, len(wav), WRITE_BLOCK_FRAMES):
                f.write(wav[i : i + WRITE_BLOCK_FRAMES])

    atomic_write(Path(path), _w)
