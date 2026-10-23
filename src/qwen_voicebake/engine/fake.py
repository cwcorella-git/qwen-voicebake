"""Deterministic GPU-free engine for tests and dry runs."""

from __future__ import annotations

import hashlib
from typing import Any

import numpy as np

from .base import AudioResult


class FakeEngine:
    """Produces a sine tone whose length is 0.35 s per word (minimum 0.4 s).

    fail maps a text to "empty", "runaway" or "nan" to inject a bad result.
    """

    def __init__(
        self,
        design_model: str = "fake-design",
        clone_model: str = "fake-clone",
        sr: int = 24000,
        fail: dict[str, str] | None = None,
    ) -> None:
        self.design_model = design_model
        self.clone_model = clone_model
        self.sr = sr
        self.fail = dict(fail or {})
        self.loaded_model: str | None = None
        self.calls: list[tuple[str, str]] = []
        self.swaps = 0

    def load(self, model_id: str) -> None:
        if self.loaded_model == model_id:
            return
        if self.loaded_model is not None:
            self.swaps += 1
        self.loaded_model = model_id

    def unload(self) -> None:
        self.loaded_model = None

    def _synth(self, text: str, seed: int) -> AudioResult:
        mode = self.fail.get(text)
        if mode == "empty":
            return AudioResult(np.zeros(0, dtype=np.float32), self.sr)
        words = len(text.split())
        seconds = max(0.4, 0.35 * words)
        if mode == "runaway":
            seconds = 30.0
        n = int(seconds * self.sr)
        digest = hashlib.sha1(f"{text}|{seed}".encode()).digest()
        freq = 150.0 + digest[0] * 2.0
        t = np.arange(n, dtype=np.float64) / self.sr
        wav = (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
        if mode == "nan":
            wav[n // 2] = np.nan
        return AudioResult(wav, self.sr)

    def design(
        self,
        text: str,
        instruct: str,
        language: str,
        seed: int,
        temperature: float,
        max_new_tokens: int,
    ) -> AudioResult:
        self.load(self.design_model)
        self.calls.append(("design", self.design_model))
        return self._synth(text, seed)

    def make_clone_prompt(self, ref_wav: np.ndarray, sr: int, ref_text: str) -> Any:
        return ("fake-prompt", len(ref_wav), sr, ref_text)

    def clone(
        self,
        text: str,
        language: str,
        prompt: Any,
        seed: int,
        temperature: float,
        max_new_tokens: int,
    ) -> AudioResult:
        self.load(self.clone_model)
        self.calls.append(("clone", self.clone_model))
        return self._synth(text, seed)

    def device_info(self) -> str:
        return "fake (no device)"
