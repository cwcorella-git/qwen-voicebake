"""Entry point: voicebake-app [--project DIR] [--fake]."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="voicebake-app", description="Desktop app for qwen-voicebake projects."
    )
    p.add_argument("--project", metavar="DIR", help="project directory (default: last opened)")
    p.add_argument("--fake", action="store_true", help="placeholder audio, no model")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print("The desktop app needs PySide6: pip install 'qwen-voicebake[app]'", file=sys.stderr)
        return 2

    from ..config import find_project_root
    from .window import run_app

    app = QApplication(sys.argv[:1])
    app.setOrganizationName("qwen-voicebake")
    app.setApplicationName("Voicebake")
    app.setApplicationDisplayName("Voicebake")

    project: Path | None = None
    if args.project:
        project = find_project_root(args.project) or Path(args.project)
    else:
        last = QSettings().value("project/last")
        if last and (Path(str(last)) / "voicebake.toml").is_file():
            project = Path(str(last))
    return run_app(app, project, args.fake)


if __name__ == "__main__":
    sys.exit(main())
