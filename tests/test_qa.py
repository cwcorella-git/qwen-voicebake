import numpy as np

from qwen_voicebake.config import QACfg
from qwen_voicebake.post import write_audio
from qwen_voicebake.qa import qa_check

SR = 1000
CFG = QACfg()


def w(seconds):
    return np.zeros(int(seconds * SR), dtype=np.float32)


def test_ok():
    r = qa_check(w(1.0), SR, "two words", "speech", CFG)
    assert r.level == "ok" and r.reasons == [] and r.duration == 1.0


def test_hard():
    assert qa_check(w(13), SR, "hi there", "speech", CFG).reasons == ["runaway"]
    r = qa_check(w(0.1), SR, "hi there", "vocal", CFG)
    assert r.level == "hard" and r.reasons == ["empty"]


def test_soft_speech():
    fast = qa_check(w(0.5), SR, "one two three four five", "speech", CFG)
    assert fast.level == "soft" and "too fast" in fast.reasons[0]
    slow = qa_check(w(5), SR, "one two", "speech", CFG)
    assert slow.level == "soft" and "too slow" in slow.reasons[0]
    one = qa_check(w(4), SR, "Hello", "speech", CFG)
    assert one.level == "soft"
    assert qa_check(w(3), SR, "Hello", "speech", CFG).level == "ok"


def test_vocal_only_hard():
    assert qa_check(w(5), SR, "Hnngh", "vocal", CFG).level == "ok"
    assert qa_check(w(0.5), SR, "a b c d e f g", "vocal", CFG).level == "ok"


def test_path(tmp_path):
    p = tmp_path / "a.wav"
    write_audio(p, np.ones(24000, dtype=np.float32) * 0.1, 24000, "wav")
    r = qa_check(p, 0, "two words", "speech", CFG)
    assert abs(r.duration - 1.0) < 1e-6 and r.level == "ok"
