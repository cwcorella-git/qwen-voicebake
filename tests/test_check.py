import json

import pytest

from qwen_voicebake.check import bundled_lexicon, looks_wordless, run_check

LEX = bundled_lexicon()


@pytest.mark.parametrize("text", ["Hrrk", "*grunt*", "[gasp]", "Mm.", "Hnngh!", "..."])
def test_wordless(text):
    assert looks_wordless(text, LEX)


@pytest.mark.parametrize("text", ["Hello there", "Okay.", "Well.", "Stop!", "Yes", "Oh", "Hey"])
def test_not_wordless(text):
    assert not looks_wordless(text, LEX)


def test_lexicon_exemption():
    assert looks_wordless("Lurk", LEX)
    assert not looks_wordless("Lurk", LEX | {"lurk"})


def test_bundled_lexicon():
    assert 200 <= len(LEX) <= 400
    assert "hm" not in LEX and "hmm" not in LEX
    assert all(w == w.lower() and w.strip() == w for w in LEX)


def _write_lines(project, lines):
    project.paths.lines.write_text(json.dumps({"version": 1, "lines": lines}))


def test_run_check(project):
    _write_lines(
        project,
        [
            {"id": "a", "voice": "mech", "tone": "warm", "text": "Back again?"},
            {"id": "b", "voice": "mech", "tone": "warm", "text": "Hrrk"},
            {"id": "c", "voice": "nobody", "tone": "nope", "text": "Hi there"},
            {
                "id": "d",
                "voice": "mech",
                "tone": "warm",
                "kind": "vocal",
                "text": "one two three four five six seven",
            },
            {"id": "e", "voice": "mech", "tone": "warm", "text": "Grrr is what the dog said"},
            {"id": "f", "voice": "mech", "tone": "warm", "text": "Grrr"},
        ],
    )
    issues = run_check(project)
    by = {(i.where, i.level) for i in issues}
    assert ("b", "warning") in by
    assert ("c", "error") in by
    assert ("d", "error") in by
    assert ("a", "warning") not in by
    msgs = [i.msg for i in issues if i.where == "c"]
    assert any("unknown voice" in m for m in msgs) and any("unknown tone" in m for m in msgs)


def test_corpus_lexicon_exempts(project):
    _write_lines(
        project,
        [
            {"id": "a", "voice": "mech", "tone": "warm", "text": "Lurk and wait"},
            {"id": "b", "voice": "mech", "tone": "warm", "text": "Lurk"},
            {"id": "c", "voice": "mech", "tone": "warm", "text": "Brrt"},
        ],
    )
    wheres = {i.where for i in run_check(project) if i.level == "warning"}
    assert wheres == {"c"}


def test_missing_files(project):
    issues = run_check(project)
    assert issues and issues[0].level == "error"
