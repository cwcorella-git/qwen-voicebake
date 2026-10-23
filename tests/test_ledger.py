from qwen_voicebake.ledger import Ledger, take_rel
from qwen_voicebake.schema import Line


def test_roundtrip_and_states(tmp_path):
    out = tmp_path / "out"
    led = Ledger.for_root(tmp_path)
    line = Line("a1", "v", "neutral", "Hi there.")
    rel = take_rel(line, "ogg")
    assert rel == "v/a1.ogg"
    assert led.line_state(line, out, "h1") == "new"
    led.mark_failed(rel, "runaway")
    assert led.line_state(line, out, "h1") == "failed"
    (out / "v").mkdir(parents=True)
    (out / rel).write_bytes(b"x")
    led.stamp(rel, "h1", "clone", 1.234, "soft", ["too slow"])
    assert rel not in led.failed
    assert led.is_current(rel, "h1") and not led.is_current(rel, "h2")
    assert led.line_state(line, out, "h1") == "ok"
    assert led.line_state(line, out, "h2") == "stale"
    led.save()
    again = Ledger.for_root(tmp_path)
    assert again.takes[rel]["qa"] == "soft" and again.takes[rel]["route"] == "clone"
    (out / (rel + ".human")).write_text("")
    assert again.line_state(line, out, "h1") == "human"
