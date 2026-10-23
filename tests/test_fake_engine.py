import numpy as np

from qwen_voicebake.engine import get_engine
from qwen_voicebake.engine.fake import FakeEngine


def test_deterministic_and_length():
    e = FakeEngine()
    a = e.design("one two three four", "i", "English", 1, 0.5, 100)
    b = e.design("one two three four", "i", "English", 1, 0.5, 100)
    assert np.array_equal(a.wav, b.wav)
    assert a.sr == 24000 and a.wav.dtype == np.float32
    assert abs(len(a.wav) / a.sr - 1.4) < 0.01
    assert len(e.design("Hi", "i", "English", 1, 0.5, 1).wav) == int(0.4 * 24000)


def test_calls_and_swaps():
    e = FakeEngine("D", "C")
    e.design("a", "i", "English", 1, 0.5, 1)
    p = e.make_clone_prompt(np.zeros(10, dtype=np.float32), 24000, "x")
    e.clone("a", "English", p, 1, 0.5, 1)
    e.clone("b", "English", p, 1, 0.5, 1)
    e.design("c", "i", "English", 1, 0.5, 1)
    assert e.calls == [("design", "D"), ("clone", "C"), ("clone", "C"), ("design", "D")]
    assert e.swaps == 2 and e.loaded_model == "D"
    e.unload()
    assert e.loaded_model is None


def test_failures():
    e = FakeEngine(fail={"e": "empty", "r": "runaway", "n": "nan"})
    assert len(e.design("e", "i", "English", 1, 0.5, 1).wav) == 0
    assert len(e.design("r", "i", "English", 1, 0.5, 1).wav) == 30 * 24000
    assert np.isnan(e.design("n", "i", "English", 1, 0.5, 1).wav).any()


def test_get_engine_fake(project):
    e = get_engine(project, fake=True)
    assert isinstance(e, FakeEngine) and e.design_model == project.engine.design_model
