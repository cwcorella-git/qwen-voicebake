"""Qwen3-TTS engine. torch and qwen_tts are imported only inside functions."""

from __future__ import annotations

import gc
import logging
from typing import TYPE_CHECKING, Any

import numpy as np

from .base import AudioResult

if TYPE_CHECKING:
    from ..config import EngineCfg

log = logging.getLogger(__name__)


def select_device(pref: str = "auto") -> str:
    """Resolve "auto" to cuda, then mps, then cpu. Other values pass through."""
    if pref != "auto":
        return pref
    import torch

    if torch.cuda.is_available():
        return "cuda"
    mps = getattr(torch.backends, "mps", None)
    if mps is not None and mps.is_available():
        return "mps"
    return "cpu"


def _dtype_for(device: str, name: str) -> Any:
    import torch

    if not device.startswith("cuda"):
        return torch.float32
    return getattr(torch, name, torch.bfloat16)


def _to_mono(wav: Any) -> np.ndarray:
    if hasattr(wav, "detach"):
        wav = wav.detach().float().cpu().numpy()
    arr = np.asarray(wav, dtype=np.float32)
    if arr.ndim > 1:
        arr = arr.reshape(-1) if 1 in arr.shape else arr.mean(axis=0)
    return arr


class QwenEngine:
    """Holds one Qwen3-TTS model at a time; design and clone load the model they need."""

    def __init__(self, cfg: EngineCfg) -> None:
        self.cfg = cfg
        self.design_model = cfg.design_model
        self.clone_model = cfg.clone_model
        self.loaded_model: str | None = None
        self._model: Any = None
        self._device: str | None = None
        self._prompts: dict[Any, Any] = {}

    # -- device and model ---------------------------------------------------------

    @property
    def device(self) -> str:
        if self._device is None:
            self._device = select_device(self.cfg.device)
        return self._device

    def _device_map(self) -> str:
        return "cuda:0" if self.device == "cuda" else self.device

    def _from_pretrained(self, model_id: str) -> Any:
        from qwen_tts import Qwen3TTSModel

        return Qwen3TTSModel.from_pretrained(
            model_id,
            device_map=self._device_map(),
            dtype=_dtype_for(self.device, self.cfg.dtype),
            attn_implementation=self.cfg.attn,
        )

    def load(self, model_id: str) -> None:
        if self.loaded_model == model_id and self._model is not None:
            return
        self.unload()
        try:
            self._model = self._from_pretrained(model_id)
        except Exception:
            if self.device != "mps":
                raise
            log.warning("loading %s on mps failed; falling back to cpu", model_id, exc_info=True)
            self._device = "cpu"
            self._model = self._from_pretrained(model_id)
        self.loaded_model = model_id

    def unload(self) -> None:
        if self._model is None and self.loaded_model is None:
            return
        self._model = None
        self.loaded_model = None
        self._prompts.clear()
        gc.collect()
        if self._device == "cuda":
            import torch

            torch.cuda.empty_cache()

    def device_info(self) -> str:
        dev = self.device
        if dev == "cuda":
            import torch

            return f"cuda ({torch.cuda.get_device_name(0)})"
        return dev

    # -- synthesis -----------------------------------------------------------------

    def _run(self, fn_name: str, seed: int, **kwargs: Any) -> AudioResult:
        import torch

        def call() -> AudioResult:
            torch.manual_seed(seed)
            wavs, sr = getattr(self._model, fn_name)(**kwargs)
            return AudioResult(_to_mono(wavs[0]), int(sr))

        try:
            return call()
        except Exception:
            if self.device != "mps":
                raise
            log.warning("synthesis on mps failed; falling back to cpu", exc_info=True)
            model_id = self.loaded_model
            self.unload()
            self._device = "cpu"
            assert model_id is not None
            self.load(model_id)
            return call()

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
        return self._run(
            "generate_voice_design",
            seed,
            text=[text],
            language=[language],
            instruct=[instruct],
            max_new_tokens=max_new_tokens,
            temperature=temperature,
        )

    def make_clone_prompt(
        self, ref_wav: np.ndarray, sr: int, ref_text: str, key: Any = None
    ) -> Any:
        """Build a reusable clone prompt. With key, the prompt is cached until the next swap.

        If the prompt API fails, the raw reference is returned and clone() passes it directly.
        """
        self.load(self.clone_model)
        if key is not None and key in self._prompts:
            return self._prompts[key]
        ref = (np.asarray(ref_wav, dtype=np.float32), int(sr))
        try:
            prompt: Any = self._model.create_voice_clone_prompt(ref_audio=ref, ref_text=ref_text)
        except Exception:
            log.warning("create_voice_clone_prompt failed; using raw reference", exc_info=True)
            prompt = _RawRef(ref, ref_text)
        if key is not None:
            self._prompts[key] = prompt
        return prompt

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
        common = {
            "text": [text],
            "language": [language],
            "max_new_tokens": max_new_tokens,
            "temperature": temperature,
        }
        if isinstance(prompt, _RawRef):
            return self._run(
                "generate_voice_clone",
                seed,
                ref_audio=[prompt.ref],
                ref_text=[prompt.ref_text],
                **common,
            )
        return self._run("generate_voice_clone", seed, voice_clone_prompt=prompt, **common)


class _RawRef:
    """Fallback clone input when the reusable prompt API is unavailable."""

    def __init__(self, ref: tuple[np.ndarray, int], ref_text: str) -> None:
        self.ref = ref
        self.ref_text = ref_text
