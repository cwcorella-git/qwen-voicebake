from qwen_voicebake.schema import Line, Voice, load_voices, save_voices, validate


def test_voices_roundtrip(tmp_path):
    v = {"a": Voice("a", "x", "y", seed=3, temperature=0.7, language="German")}
    save_voices(tmp_path / "v.json", v)
    assert load_voices(tmp_path / "v.json") == v


def test_validate(project):
    voices = {"mech": Voice("mech", "x", "y")}
    tones = {"warm": ""}
    lines = [
        Line("ok", "mech", "warm", "Hi"),
        Line("ok", "mech", "warm", "Hi"),
        Line("bad id!", "mech", "warm", "Hi"),
        Line("k", "mech", "warm", "Hi", kind="shout"),
        Line("e", "mech", "warm", "  "),
    ]
    msgs = [str(i) for i in validate(project, voices, lines, tones)]
    assert any("duplicate id" in m for m in msgs)
    assert any("id may only" in m for m in msgs)
    assert any("kind must be" in m for m in msgs)
    assert any("empty text" in m for m in msgs)
