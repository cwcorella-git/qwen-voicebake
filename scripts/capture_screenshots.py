"""Capture README screenshots of the desktop app.

Copies the starter example to a temporary folder, opens it with the placeholder engine
(no model, no GPU), bakes, designs candidates, and saves one PNG per view to docs/images/.
Runs offscreen at 960x600 and 1x scale. Pillow, if installed, shrinks the files.

    python scripts/capture_screenshots.py [--out docs/images]
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["QT_SCALE_FACTOR"] = "1"
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"

REPO = Path(__file__).resolve().parents[1]
SIZE = (960, 600)


def _shrink(path: Path) -> None:
    try:
        from PIL import Image
    except ImportError:
        return
    img = Image.open(path).convert("RGB")
    img = img.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    img.save(path, optimize=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(REPO / "docs" / "images"))
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    from PySide6.QtCore import QStandardPaths
    from PySide6.QtWidgets import QApplication

    QStandardPaths.setTestModeEnabled(True)  # leave the user's settings alone
    app = QApplication(sys.argv[:1])
    app.setOrganizationName("qwen-voicebake-screenshots")
    app.setApplicationName("Voicebake")

    from qwen_voicebake.app.window import MainWindow

    def pump(seconds: float = 0.2) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(0.01)

    def wait_idle(win: MainWindow) -> None:
        end = time.monotonic() + 60
        while win._busy and time.monotonic() < end:
            pump(0.05)
        pump(0.2)

    def shot(win: MainWindow, name: str) -> None:
        pump()
        path = out / f"{name}.png"
        win.grab().save(str(path))
        _shrink(path)
        print(f"{path}  {path.stat().st_size // 1024} KB")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "starter"
        shutil.copytree(REPO / "examples" / "starter", root)

        welcome = MainWindow(None, fake=True)
        welcome.setFixedSize(*SIZE)
        welcome.show()
        shot(welcome, "welcome")
        welcome.close()

        win = MainWindow(root, fake=True)
        win.setFixedSize(*SIZE)
        win.show()
        pump()
        win.bake_changed()
        wait_idle(win)
        win.refs_tab.voice.setCurrentText("mechanic")
        win.refs_tab.generate.click()
        wait_idle(win)
        win.statusBar().clearMessage()

        win.tabs.setCurrentWidget(win.voices_tab)
        shot(win, "voices")
        win.tabs.setCurrentWidget(win.lines_tab)
        win.lines_tab.table.selectRow(1)
        shot(win, "lines")
        win.tabs.setCurrentWidget(win.refs_tab)
        shot(win, "references")
        win.tabs.setCurrentWidget(win.bake_tab)
        shot(win, "bake")
        win.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
