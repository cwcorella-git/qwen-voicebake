"""Project checks that need no GPU and no torch."""

from __future__ import annotations

import json
import re
from importlib import resources
from typing import TYPE_CHECKING

from .lines_io import load_lines
from .schema import Issue, Line, load_voices, validate
from .tones import load_project_tones

if TYPE_CHECKING:
    from .config import Project

VOWELS = set("aeiouy")
MAX_VOCAL_WORDS = 6
_STAR_RE = re.compile(r"^\*[^*]+\*$")
_BRACKET_RE = re.compile(r"^\[[^\]]+\]$")
_TOKEN_RE = re.compile(r"[a-z']+")


def _tokens(text: str) -> list[str]:
    return [t.strip("'") for t in _TOKEN_RE.findall(text.lower()) if t.strip("'")]


def bundled_lexicon() -> set[str]:
    """Common English words shipped with the package."""
    data = resources.files("qwen_voicebake").joinpath("data", "common_words.txt")
    text = data.read_text(encoding="utf-8")
    return {w.strip().lower() for w in text.splitlines() if w.strip()}


def corpus_lexicon(lines: list[Line]) -> set[str]:
    """Words that appear in multi-word speech lines of the project itself."""
    words: set[str] = set()
    for line in lines:
        if line.kind != "speech":
            continue
        toks = _tokens(line.text)
        if len(toks) >= 2:
            words.update(toks)
    return words


def looks_wordless(text: str, lexicon: set[str] | frozenset[str] = frozenset()) -> bool:
    """True if text looks like a sound or stage direction rather than a spoken word.

    Flags "*grunt*" and "[gasp]", text with no letters, a single token without a vowel
    (aeiouy), and a short single token (4 letters or fewer) whose consonants are at least
    twice its vowels, unless the token is in the lexicon.
    """
    stripped = text.strip()
    if not stripped:
        return False
    if _STAR_RE.match(stripped) or _BRACKET_RE.match(stripped):
        return True
    toks = _tokens(stripped)
    if not toks:
        return True
    if len(toks) != 1:
        return False
    tok = toks[0]
    letters = [c for c in tok if c.isalpha()]
    vowels = sum(1 for c in letters if c in VOWELS)
    consonants = len(letters) - vowels
    if vowels == 0:
        return True
    return len(letters) <= 4 and consonants >= 2 * vowels and tok not in lexicon


def run_check(project: Project) -> list[Issue]:
    """Validate the project files and flag lines that are probably mis-typed."""
    issues: list[Issue] = []
    try:
        voices = load_voices(project.paths.voices)
    except (OSError, json.JSONDecodeError) as e:
        return [Issue("error", str(project.paths.voices), f"cannot read voices: {e}")]
    try:
        tones = load_project_tones(project)
    except (OSError, ValueError) as e:
        return [Issue("error", str(project.paths.tones), f"cannot read tones: {e}")]
    try:
        lines = load_lines(project)
    except (OSError, ValueError, KeyError, AttributeError, ImportError) as e:
        return [Issue("error", str(project.paths.lines), f"cannot read lines: {e}")]

    issues.extend(validate(project, voices, lines, tones))
    lexicon = bundled_lexicon() | corpus_lexicon(lines)
    for line in lines:
        where = line.id or "(no id)"
        if line.kind == "speech" and looks_wordless(line.text, lexicon):
            issues.append(
                Issue("warning", where, f'"{line.text}" looks wordless; mark kind: vocal')
            )
        elif line.kind == "vocal" and len(line.text.split()) > MAX_VOCAL_WORDS:
            issues.append(
                Issue("error", where, f"vocal line has more than {MAX_VOCAL_WORDS} words")
            )
    return issues
