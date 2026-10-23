"""Audio playback for takes, references and candidates."""

from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Signal


class Player(QObject):
    """Plays one file at a time. If the media backend cannot decode it, the file is decoded
    with soundfile into a temporary WAV and played again."""

    error = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._player = None
        self._output = None
        self._current: Path | None = None
        self._fallback_used = False
        self._tmpdir = tempfile.TemporaryDirectory(prefix="voicebake-play-")
        try:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

            self._output = QAudioOutput(self)
            self._player = QMediaPlayer(self)
            self._player.setAudioOutput(self._output)
            self._player.errorOccurred.connect(self._on_error)
        except Exception:  # noqa: BLE001 - playback is optional
            self._player = None

    @property
    def available(self) -> bool:
        return self._player is not None

    def play(self, path: str | Path) -> None:
        path = Path(path)
        if not path.is_file():
            self.error.emit(f"File not found: {path}")
            return
        if self._player is None:
            self.error.emit("Audio playback is not available on this system.")
            return
        self._current = path
        self._fallback_used = False
        self._start(path)

    def stop(self) -> None:
        if self._player is not None:
            self._player.stop()

    def _start(self, path: Path) -> None:
        assert self._player is not None
        self._player.stop()
        self._player.setSource(QUrl.fromLocalFile(str(path)))
        self._player.play()

    def _on_error(self, *_: object) -> None:
        if self._current is None or self._fallback_used:
            msg = self._player.errorString() if self._player is not None else ""
            self.error.emit(f"Could not play {self._current}: {msg}")
            return
        self._fallback_used = True
        try:
            import soundfile as sf

            wav, sr = sf.read(str(self._current), dtype="float32", always_2d=False)
            tmp = Path(self._tmpdir.name) / "play.wav"
            sf.write(str(tmp), wav, sr, subtype="PCM_16")
        except Exception as e:  # noqa: BLE001
            self.error.emit(f"Could not play {self._current}: {e}")
            return
        self._start(tmp)

    def close(self) -> None:
        self.stop()
        self._tmpdir.cleanup()
