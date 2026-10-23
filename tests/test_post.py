import numpy as np
import pytest
import soundfile as sf

from qwen_voicebake.post import EmptyAudioError, postprocess, write_audio

SR = 24000


def tone(seconds, amp=0.5):
    return (amp * np.sin(np.arange(int(seconds * SR)) * 0.1)).astype(np.float32)


def test_nan_and_clip():
    w = tone(0.5)
    w[100] = np.nan
    w[200] = 5.0
    w[300] = -np.inf
    out = postprocess(w, SR)
    assert np.isfinite(out).all()
    assert out.max() <= 1.0 and out.min() >= -1.0
    assert out.dtype == np.float32 and out.flags["C_CONTIGUOUS"]


def test_trim_and_pad():
    w = np.concatenate([np.zeros(SR), tone(0.5), np.zeros(SR)])
    out = postprocess(w, SR)
    pad = int(0.03 * SR)
    assert abs(len(out) - (int(0.5 * SR) + 2 * pad)) <= 2
    assert np.abs(out[: pad // 2]).max() <= 0.01


def test_silence_becomes_empty():
    assert postprocess(np.zeros(SR), SR).size == 0


def test_empty_audio_error(tmp_path):
    for w in (np.zeros(0, dtype=np.float32), np.zeros(100, dtype=np.float32)):
        with pytest.raises(EmptyAudioError):
            write_audio(tmp_path / "x.ogg", w, SR, "ogg")
    assert not (tmp_path / "x.ogg").exists()


@pytest.mark.parametrize("fmt", ["ogg", "wav"])
def test_write_roundtrip(tmp_path, fmt):
    w = tone(0.5)
    p = tmp_path / "sub" / f"t.{fmt}"
    write_audio(p, w, SR, fmt)
    data, sr = sf.read(p, dtype="float32")
    assert sr == SR
    assert abs(len(data) - len(w)) <= 2
    assert sf.info(p).format == fmt.upper()
    assert [f.name for f in p.parent.iterdir()] == [p.name]


def test_bad_format(tmp_path):
    with pytest.raises(ValueError):
        write_audio(tmp_path / "x.mp3", tone(0.5), SR, "mp3")


def test_normalize():
    pytest.importorskip("pyloudnorm")
    import pyloudnorm

    w = tone(2.0, 0.05)
    out = postprocess(w, SR, True)
    assert abs(pyloudnorm.Meter(SR).integrated_loudness(out) - (-18.0)) < 0.5
    out2 = postprocess(w, SR, -23.0)
    assert abs(pyloudnorm.Meter(SR).integrated_loudness(out2) - (-23.0)) < 0.5
