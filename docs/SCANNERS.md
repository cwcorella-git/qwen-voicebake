# Scanners

A scanner is a Python script that reads your lines from the game's own files, such as
scripts, dialogue data or spreadsheets exported to JSON. With a scanner the game source
is the only place the lines live, and there is no `lines.json` to keep in sync.

## Contract

Set the script path under `[paths]` in `voicebake.toml`, relative to the project folder:

```toml
[paths]
scanner = "tools/my_scanner.py"
```

When `scanner` is set, the lines file is ignored.

The script must define one function:

```python
def scan(project_dir: pathlib.Path) -> list[dict]:
    ...
```

- `project_dir` is the folder that holds `voicebake.toml`, as an absolute path.
- It returns one dict per line, with the same keys as an entry in `lines.json`:

| Key | Required | Default |
|---|---|---|
| `id` | yes | |
| `voice` | yes | |
| `text` | yes | |
| `tone` | no | `neutral` |
| `kind` | no | `speech` |
| `direction` | no | empty |

Missing, `None` or blank optional values get the default. Surrounding whitespace is
stripped from every value except `text`.

The returned lines are checked like any other: ids must be unique and use only letters,
digits, `_`, `.` and `-`; voices and tones must exist; `kind` must be `speech` or `vocal`.
Run `voicebake check` after writing a scanner.

When it runs:

- The script is imported and `scan` is called every time `check`, `bake`, `status` or
  `refs status` runs, and when the app opens or reloads the project, and on each request
  to the app's local API that needs line states.
- It runs in the same Python process as qwen-voicebake, with full access to your files.
  Only point `scanner` at code you trust.
- Keep it fast and free of side effects. It should only read files.
- If it raises an exception, the command fails with that error.

In the app, lines from a scanner are shown read-only. Edit them in the game source and use
File > Reload.

## Worked example

The starter project includes `tools/example_scanner.py` and a game script
`game/shopkeeper.gd`. The game script calls a function `say(voice, id, tone, text)`:

```gdscript
func greet() -> void:
	say("mechanic", "mech_greet_01", "warm", "Back again? Pull up a stool, the kettle is on.")
```

The scanner finds every such call in `game/*.gd` with a regular expression:

```python
import re
from pathlib import Path

SAY_RE = re.compile(
    r'say\(\s*"(?P<voice>[^"]+)"\s*,\s*"(?P<id>[^"]+)"\s*,\s*"(?P<tone>[^"]+)"\s*,'
    r'\s*"(?P<text>(?:[^"\\]|\\.)*)"\s*\)'
)


def scan(project_dir: Path) -> list[dict]:
    lines: list[dict] = []
    for path in sorted(Path(project_dir, "game").rglob("*.gd")):
        source = path.read_text(encoding="utf-8")
        for m in SAY_RE.finditer(source):
            lines.append(
                {
                    "id": m["id"],
                    "voice": m["voice"],
                    "tone": m["tone"],
                    "text": m["text"].replace('\\"', '"'),
                }
            )
    return lines
```

To try it in a project made with `voicebake init`:

1. Set `scanner = "tools/example_scanner.py"` in `voicebake.toml`.
2. Run `voicebake check`. It now sees the three lines in `game/shopkeeper.gd` instead of
   the twelve in `lines.json`.
3. Run `voicebake bake --dry-run` to see the plan.

## Another example: JSON dialogue data

If your dialogue is stored as data, the scanner maps your format to line dicts. For a file
`game/dialogue.json` shaped like
`{"nodes": [{"key": "intro_1", "speaker": "clerk", "mood": "nervous", "line": "Hello?"}]}`:

```python
import json
from pathlib import Path


def scan(project_dir: Path) -> list[dict]:
    data = json.loads((project_dir / "game" / "dialogue.json").read_text(encoding="utf-8"))
    return [
        {
            "id": node["key"],
            "voice": node["speaker"],
            "tone": node.get("mood") or "neutral",
            "text": node["line"],
            "kind": "vocal" if node.get("is_sound") else "speech",
        }
        for node in data["nodes"]
        if node.get("line")
    ]
```

## Tips

- Sort the files you read so the line order stays the same between runs.
- Skip entries without text rather than returning empty `text`; empty text is a check
  error.
- If your ids contain characters outside `A-Z a-z 0-9 _ . -`, convert them in the
  scanner. The id becomes the file name.
- Renaming an id in the game source creates a new line. The old file stays in the output
  folder until you delete it, and the manifest no longer lists it.
