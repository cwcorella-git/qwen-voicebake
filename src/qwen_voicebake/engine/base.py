"""Engine interface shared by the real Qwen engine and the test fake."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np


@dataclass
class AudioResult:
    wav: np.ndarray  # float32, mono
    sr: int


class Engine(Protocol):
    loaded_model: str | None

    def load(self, model_id: str) -> None: ...

    def unload(self) -> None: ...

    def design(
        self,
        text: str,
        instruct: str,
        language: str,
        seed: int,
        temperature: float,
        max_new_tokens: int,
    ) -> AudioResult: ...

    def make_clone_prompt(self, ref_wav: np.ndarray, sr: int, ref_text: str) -> Any: ...

    def clone(
        self,
        text: str,
        language: str,
        prompt: Any,
        seed: int,
        temperature: float,
        max_new_tokens: int,
    ) -> AudioResult: ...

    def device_info(self) -> str: ...
