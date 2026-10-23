"""Engine selection."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import AudioResult, Engine

if TYPE_CHECKING:
    from ..config import Project

__all__ = ["AudioResult", "Engine", "get_engine"]


def get_engine(project: Project, fake: bool = False) -> Engine:
    """Return the fake engine, or the Qwen engine (imported lazily so torch stays optional)."""
    if fake:
        from .fake import FakeEngine

        return FakeEngine(project.engine.design_model, project.engine.clone_model)
    from .qwen import QwenEngine

    return QwenEngine(project.engine)
