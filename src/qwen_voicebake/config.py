"""Project configuration: voicebake.toml loading and path resolution."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

CONFIG_NAME = "voicebake.toml"


class ConfigError(ValueError):
    """Raised for an invalid or missing project configuration."""


@dataclass
class EngineCfg:
    design_model: str = "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign"
    clone_model: str = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
    language: str = "English"
    temperature: float = 0.5
    device: str = "auto"
    dtype: str = "bfloat16"
    attn: str = "sdpa"
    max_new_tokens: int = 2048
    vocal_max_new_tokens: int = 48


@dataclass
class PathsCfg:
    voices: Path
    lines: Path
    scanner: Path | None
    tones: Path
    refs: Path
    out: Path
    format: str = "ogg"
    normalize: bool | float = False


@dataclass
class QACfg:
    max_seconds: float = 12.0
    min_seconds: float = 0.2
    sec_per_word: tuple[float, float] = (0.12, 1.2)
    one_word_max: float = 3.5


@dataclass
class AppCfg:
    port: int = 47811


@dataclass
class Project:
    root: Path
    engine: EngineCfg = field(default_factory=EngineCfg)
    paths: PathsCfg = None  # type: ignore[assignment]
    qa: QACfg = field(default_factory=QACfg)
    app: AppCfg = field(default_factory=AppCfg)

    def __post_init__(self) -> None:
        if self.paths is None:
            self.paths = _default_paths(self.root, {})

    @property
    def state_dir(self) -> Path:
        return self.root / ".voicebake"


def find_project_root(start: str | Path) -> Path | None:
    """Return the nearest directory at or above start that holds voicebake.toml."""
    p = Path(start).resolve()
    if p.is_file():
        p = p.parent
    for d in (p, *p.parents):
        if (d / CONFIG_NAME).is_file():
            return d
    return None


def _fill(cls: type, data: dict[str, Any], section: str) -> Any:
    names = {f.name for f in fields(cls)}
    unknown = set(data) - names
    if unknown:
        raise ConfigError(f"[{section}] unknown keys: {', '.join(sorted(unknown))}")
    try:
        return cls(**data)
    except TypeError as e:  # pragma: no cover
        raise ConfigError(f"[{section}] {e}") from e


def _resolve(root: Path, value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else (root / p)


def _default_paths(root: Path, data: dict[str, Any]) -> PathsCfg:
    scanner = data.get("scanner", "") or ""
    normalize = data.get("normalize", False)
    if isinstance(normalize, bool) or isinstance(normalize, (int, float)):
        pass
    else:
        raise ConfigError("[paths] normalize must be false, true or a LUFS number")
    fmt = data.get("format", "ogg")
    if fmt not in ("ogg", "wav"):
        raise ConfigError("[paths] format must be 'ogg' or 'wav'")
    known = {"voices", "lines", "scanner", "tones", "refs", "out", "format", "normalize"}
    unknown = set(data) - known
    if unknown:
        raise ConfigError(f"[paths] unknown keys: {', '.join(sorted(unknown))}")
    return PathsCfg(
        voices=_resolve(root, data.get("voices", "voices.json")),
        lines=_resolve(root, data.get("lines", "lines.json")),
        scanner=_resolve(root, scanner) if scanner else None,
        tones=_resolve(root, data.get("tones", "tones.toml") or "tones.toml"),
        refs=_resolve(root, data.get("refs", "refs")),
        out=_resolve(root, data.get("out", "voice")),
        format=fmt,
        normalize=normalize if isinstance(normalize, bool) else float(normalize),
    )


def load_project(directory: str | Path) -> Project:
    """Load voicebake.toml from directory. Relative paths resolve against that directory."""
    root = Path(directory).resolve()
    cfg_path = root / CONFIG_NAME
    if not cfg_path.is_file():
        raise ConfigError(f"no {CONFIG_NAME} in {root}")
    try:
        with open(cfg_path, "rb") as f:
            raw = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{cfg_path}: {e}") from e
    unknown = set(raw) - {"engine", "paths", "qa", "app"}
    if unknown:
        raise ConfigError(f"unknown sections: {', '.join(sorted(unknown))}")
    qa_raw = dict(raw.get("qa", {}))
    if "sec_per_word" in qa_raw:
        spw = qa_raw["sec_per_word"]
        if not (isinstance(spw, (list, tuple)) and len(spw) == 2):
            raise ConfigError("[qa] sec_per_word must be [low, high]")
        qa_raw["sec_per_word"] = (float(spw[0]), float(spw[1]))
    return Project(
        root=root,
        engine=_fill(EngineCfg, dict(raw.get("engine", {})), "engine"),
        paths=_default_paths(root, dict(raw.get("paths", {}))),
        qa=_fill(QACfg, qa_raw, "qa"),
        app=_fill(AppCfg, dict(raw.get("app", {})), "app"),
    )
