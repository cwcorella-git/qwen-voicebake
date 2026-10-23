"""Command line interface: voicebake init | check | bake | refs | status."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Sequence
from importlib import resources
from pathlib import Path
from typing import Any

from .config import ConfigError, Project, find_project_root, load_project

EXIT_OK = 0
EXIT_CHECK = 1
EXIT_USAGE = 2
EXIT_LOCKED = 3


class CliError(Exception):
    def __init__(self, msg: str, code: int = EXIT_USAGE) -> None:
        super().__init__(msg)
        self.code = code


def _err(msg: str) -> None:
    print(msg, file=sys.stderr)


# -- helpers -------------------------------------------------------------------------


def _open_project(args: argparse.Namespace) -> Project:
    if args.project:
        root: Path | None = Path(args.project)
    else:
        root = find_project_root(Path.cwd())
    if root is None:
        raise CliError("no voicebake.toml found here or in a parent directory (see --project)")
    try:
        return load_project(root)
    except ConfigError as e:
        raise CliError(str(e)) from e


def _load_all(project: Project):
    from .ledger import Ledger
    from .lines_io import load_lines
    from .schema import load_voices
    from .tones import load_project_tones

    try:
        voices = load_voices(project.paths.voices)
        tones = load_project_tones(project)
        lines = load_lines(project)
        ledger = Ledger.for_root(project.root)
    except (OSError, ValueError, KeyError, AttributeError, ImportError) as e:
        raise CliError(f"cannot read project files: {e}") from e
    return voices, lines, tones, ledger


def _run_check(project: Project) -> tuple[list, int, int]:
    from .check import run_check

    issues = run_check(project)
    errors = sum(1 for i in issues if i.level == "error")
    return issues, errors, len(issues) - errors


def _copy_tree(src: Any, dst: Path) -> list[Path]:
    written: list[Path] = []
    dst.mkdir(parents=True, exist_ok=True)
    for entry in src.iterdir():
        if entry.name == "__pycache__":
            continue
        target = dst / entry.name
        if entry.is_dir():
            written.extend(_copy_tree(entry, target))
        else:
            target.write_bytes(entry.read_bytes())
            written.append(target)
    return written


def _planned(args: argparse.Namespace, project: Project):
    from .planner import plan

    voices, lines, tones, ledger = _load_all(project)
    only_v = [v for v in args.voices.split(",") if v] if args.voices else None
    only_l = [g for g in args.lines.split(",") if g] if args.lines else None
    return plan(
        project,
        voices,
        lines,
        tones,
        ledger,
        only_voices=only_v,
        only_lines=only_l,
        force=args.force,
        force_refs=args.force_refs,
    )


# -- commands ------------------------------------------------------------------------


def init_project(dest: Path, example: str = "starter") -> list[Path]:
    """Copy a bundled example into dest. Raises CliError rather than overwrite anything."""
    if (dest / "voicebake.toml").exists():
        raise CliError(f"{dest / 'voicebake.toml'} already exists; not overwriting")
    src = resources.files("qwen_voicebake").joinpath("templates", example)
    if not src.is_dir():
        raise CliError(f"unknown example '{example}'")
    existing = [p for p in _walk_names(src) if (dest / p).exists()]
    if existing:
        raise CliError(f"would overwrite: {', '.join(existing)}")
    return _copy_tree(src, dest)


def cmd_init(args: argparse.Namespace) -> int:
    dest = Path(args.dir)
    written = init_project(dest, args.example)
    print(f"created {len(written)} files in {dest.resolve()}")
    print("next: cd there, then run `voicebake check` and `voicebake bake --dry-run`")
    return EXIT_OK


def _walk_names(src: Any, prefix: str = "") -> list[str]:
    names: list[str] = []
    for entry in src.iterdir():
        if entry.name == "__pycache__":
            continue
        rel = f"{prefix}{entry.name}"
        if entry.is_dir():
            names.extend(_walk_names(entry, rel + "/"))
        else:
            names.append(rel)
    return names


def cmd_check(args: argparse.Namespace) -> int:
    project = _open_project(args)
    issues, errors, warnings = _run_check(project)
    for issue in issues:
        print(issue)
    print(f"{errors} error(s), {warnings} warning(s)")
    if errors or (args.strict and warnings):
        return EXIT_CHECK
    return EXIT_OK


def _print_event(e: dict[str, Any]) -> None:
    kind = e.get("type")
    if kind == "ref":
        print(f"ref   {e['voice']}/{e['tone']}  via design  {e.get('duration', 0):.2f} s")
    elif kind == "warn":
        print(f"warn  {e.get('voice', '')}/{e.get('tone', '')}  {e.get('msg', '')}")
    elif kind == "take":
        if e["ok"]:
            note = f"  [{e['qa']}: {', '.join(e['reasons'])}]" if e["qa"] == "soft" else ""
            print(f"take  {e['line_id']}  via {e['route']}  {e['duration']:.2f} s{note}")
        else:
            print(f"fail  {e['line_id']}  via {e['route']}  {e['error']}")


def cmd_bake(args: argparse.Namespace) -> int:
    from .bake import Baker

    if args.fake and args.dry_run:
        _err("--fake has no effect with --dry-run (a dry run uses no engine); drop one of them")
        return EXIT_USAGE
    project = _open_project(args)
    _, errors, _ = _run_check(project)
    if errors:
        _err("project has check errors; run `voicebake check`")
        return EXIT_CHECK
    plan = _planned(args, project)

    if args.dry_run:
        jobs = plan.jobs[: args.limit] if args.limit is not None else plan.jobs

        def on_plan(e: dict[str, Any]) -> None:
            if e.get("type") == "plan":
                print(f"{e['state']:<7}{e['route']:<8}{e['line_id']}")

        needed = {(j.voice.name, j.line.tone) for j in jobs if j.route == "clone"}
        for voice, tone in plan.ref_pairs:
            if (voice, tone) in needed:
                print(f"ref    design  {voice}/{tone}  (if missing or stale)")
        s = Baker(None, project, on_plan).run(plan, dry_run=True, limit=args.limit)
        print(
            f"dry run: {s.planned} to bake, {len(s.up_to_date)} up to date, "
            f"{len(s.skipped_human)} human"
        )
        return EXIT_OK

    from .lockfile import LockHeld, ProjectLock

    try:
        with ProjectLock(project.root, "cli"):
            from .engine import get_engine

            engine = get_engine(project, fake=args.fake)
            s = Baker(engine, project, _print_event).run(plan, limit=args.limit)
    except LockHeld as e:
        _err(f"{e}; close the other session or wait for it to finish")
        return EXIT_LOCKED
    print(
        f"baked {len(s.baked)}, failed {len(s.failed)}, up to date {len(s.up_to_date)}, "
        f"human {len(s.skipped_human)}, soft QA {len(s.soft)}, {s.seconds:.1f} s"
    )
    return EXIT_CHECK if s.failed else EXIT_OK


def cmd_refs(args: argparse.Namespace) -> int:
    from . import refs as refs_mod

    project = _open_project(args)
    voices, lines, tones, _ = _load_all(project)
    action = args.refs_cmd

    if action in ("candidates", "pick", "pin", "unpin"):
        if args.voice not in voices:
            raise CliError(f"unknown voice '{args.voice}'")
        if args.tone not in tones:
            raise CliError(f"unknown tone '{args.tone}'")

    if action == "status":
        from .planner import route_for

        if args.voice and args.voice not in voices:
            raise CliError(f"unknown voice '{args.voice}'")

        lock = refs_mod.load_lock(project)
        pairs = sorted(
            {(ln.voice, ln.tone) for ln in lines if route_for(ln) == "clone" and ln.voice in voices}
        )
        for voice, tone in pairs:
            if args.voice and voice != args.voice:
                continue
            if tone not in tones:
                continue
            st = refs_mod.ref_status(project, voices[voice], tone, tones[tone], lock)
            print(f"{voice}/{tone:<14}{st}")
        return EXIT_OK

    if action == "pick":
        dst = refs_mod.pick_candidate(project, args.voice, args.tone, args.seed, voices, tones)
        print(f"pinned {args.voice}/{args.tone} from seed {args.seed}: {dst}")
        return EXIT_OK

    if action in ("pin", "unpin"):
        refs_mod.set_pinned(project, args.voice, args.tone, action == "pin")
        print(f"{args.voice}/{args.tone}: {action}")
        return EXIT_OK

    # candidates
    from .engine import get_engine
    from .lockfile import LockHeld, ProjectLock

    seeds = None
    if args.seeds:
        try:
            seeds = [int(x) for x in args.seeds.split(",") if x.strip()]
        except ValueError as e:
            raise CliError("--seeds must be comma-separated integers") from e
    try:
        with ProjectLock(project.root, "cli"):
            engine = get_engine(project, fake=args.fake)
            paths = refs_mod.gen_candidates(
                engine, project, args.voice, args.tone, args.n, seeds, voices, tones
            )
    except LockHeld as e:
        _err(str(e))
        return EXIT_LOCKED
    for p in paths:
        print(p)
    print(f"pick one with: voicebake refs pick {args.voice} {args.tone} SEED")
    return EXIT_OK


def cmd_status(args: argparse.Namespace) -> int:
    args.voices = args.lines = None
    args.force = args.force_refs = False
    project = _open_project(args)
    plan = _planned(args, project)
    counts = Counter(j.state for j in plan.jobs)
    print(f"lines: {len(plan.lines)}")
    for state in ("new", "stale", "failed"):
        print(f"  {state:<8}{counts.get(state, 0)}")
    print(f"  ok      {len(plan.up_to_date)}")
    print(f"  human   {len(plan.skipped_human)}")
    from .lockfile import holder

    h = holder(project.root)
    if h:
        print(f"locked by {h.get('owner')} (pid {h.get('pid')})")
    manifest = project.paths.out / "manifest.json"
    print(f"manifest: {'present' if manifest.is_file() else 'missing'} ({manifest})")
    return EXIT_OK


# -- parser --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--project", default=argparse.SUPPRESS, metavar="DIR", help="project directory"
    )

    p = argparse.ArgumentParser(
        prog="voicebake",
        description="Bake game dialogue into audio files with Qwen3-TTS.",
        parents=[common],
    )
    p.set_defaults(project=None)
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("init", help="create a new project from an example", parents=[common])
    s.add_argument("dir", nargs="?", default=".", metavar="DIR")
    s.add_argument("--example", default="starter", choices=["starter"])
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("check", help="validate project files", parents=[common])
    s.add_argument("--strict", action="store_true", help="warnings also fail")
    s.set_defaults(func=cmd_check)

    s = sub.add_parser(
        "bake",
        help="synthesize changed lines",
        description="Synthesize changed lines. Exit codes: 0 ok; 1 check errors or failed "
        "takes; 2 usage error; 3 project locked by another process.",
        parents=[common],
    )
    s.add_argument("--voices", help="comma-separated voice names")
    s.add_argument("--lines", help="comma-separated line id globs")
    s.add_argument("--force", action="store_true", help="re-bake lines that are up to date")
    s.add_argument("--force-refs", action="store_true", help="redesign unpinned references")
    s.add_argument("--dry-run", action="store_true", help="print the plan; synthesize nothing")
    s.add_argument("--limit", type=int, metavar="N", help="bake at most N lines")
    s.add_argument("--fake", action="store_true", help="placeholder audio, no model")
    s.set_defaults(func=cmd_bake)

    s = sub.add_parser("refs", help="manage reference clips", parents=[common])
    rsub = s.add_subparsers(dest="refs_cmd", required=True)
    r = rsub.add_parser("status", help="list reference status", parents=[common])
    r.add_argument("--voice")
    r = rsub.add_parser("candidates", help="design candidate references", parents=[common])
    r.add_argument("voice")
    r.add_argument("tone")
    r.add_argument("-n", type=int, default=4)
    r.add_argument("--seeds", help="comma-separated seeds")
    r.add_argument("--fake", action="store_true", help="placeholder audio, no model")
    r = rsub.add_parser("pick", help="use a candidate as the (pinned) reference", parents=[common])
    r.add_argument("voice")
    r.add_argument("tone")
    r.add_argument("seed", type=int)
    for name in ("pin", "unpin"):
        r = rsub.add_parser(name, help=f"{name} a reference", parents=[common])
        r.add_argument("voice")
        r.add_argument("tone")
    s.set_defaults(func=cmd_refs)

    s = sub.add_parser("status", help="show how many lines need baking", parents=[common])
    s.set_defaults(func=cmd_status)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except CliError as e:
        _err(f"error: {e}")
        return e.code
    except json.JSONDecodeError as e:
        _err(f"error: invalid JSON: {e}")
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
