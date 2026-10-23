"""Write docs/TONES.md from BUILTIN_TONES. With --check, exit 1 if the file is out of date."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from qwen_voicebake.tones import BUILTIN_TONES

OUT = Path(__file__).resolve().parent.parent / "docs" / "TONES.md"

INTRO = """\
# Tones

A tone is a short phrase appended to a voice's description. It tells the model how the
line should be delivered. Every line names one tone. The full instruction sent to the
model is the voice description, then the tone text, then the line's optional direction.

The tone `neutral` adds nothing.

## Adding or overriding a tone

Create `tones.toml` next to `voicebake.toml` (the path is `paths.tones`). Entries in the
`[tones]` table are added to the built-in list, and an entry with a built-in name replaces it:

```toml
[tones]
grumpy = "Right now: irritable and short, muttering through the words."
cold = "Right now: icy and formal."
```

A leading space is added for you. Changing a tone's text makes every take that uses it stale.

## Built-in tones

| Tone | Text |
|---|---|
"""


def render() -> str:
    rows = []
    for name, text in BUILTIN_TONES.items():
        shown = text.strip() or "(adds nothing)"
        rows.append(f"| `{name}` | {shown} |")
    return INTRO + "\n".join(rows) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="exit 1 if docs/TONES.md is stale")
    args = ap.parse_args()
    text = render()
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.is_file() else ""
        if current != text:
            print("docs/TONES.md is out of date; run scripts/gen_tones_md.py", file=sys.stderr)
            return 1
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
