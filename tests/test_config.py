import pytest

from qwen_voicebake.config import ConfigError, find_project_root, load_project


def test_defaults(tmp_path):
    (tmp_path / "voicebake.toml").write_text("")
    p = load_project(tmp_path)
    assert p.engine.temperature == 0.5
    assert p.engine.vocal_max_new_tokens == 48
    assert p.paths.voices == tmp_path.resolve() / "voices.json"
    assert p.paths.scanner is None
    assert p.paths.format == "ogg"
    assert p.paths.normalize is False
    assert p.qa.sec_per_word == (0.12, 1.2)
    assert p.app.port == 47811


def test_overrides_and_relative_paths(tmp_path):
    (tmp_path / "voicebake.toml").write_text(
        '[engine]\nlanguage = "German"\n[paths]\nout = "../game/voice"\nnormalize = -20\n'
        'format = "wav"\nscanner = "tools/s.py"\n[qa]\nsec_per_word = [0.1, 2]\n'
    )
    p = load_project(tmp_path)
    assert p.engine.language == "German"
    assert p.paths.out == tmp_path.resolve() / "../game/voice"
    assert p.paths.normalize == -20.0
    assert p.paths.format == "wav"
    assert p.paths.scanner == tmp_path.resolve() / "tools/s.py"
    assert p.qa.sec_per_word == (0.1, 2.0)


def test_errors(tmp_path):
    with pytest.raises(ConfigError):
        load_project(tmp_path)
    (tmp_path / "voicebake.toml").write_text("[engine]\nbogus = 1\n")
    with pytest.raises(ConfigError):
        load_project(tmp_path)
    (tmp_path / "voicebake.toml").write_text('[paths]\nformat = "mp3"\n')
    with pytest.raises(ConfigError):
        load_project(tmp_path)


def test_find_project_root(tmp_path):
    (tmp_path / "voicebake.toml").write_text("")
    sub = tmp_path / "a" / "b"
    sub.mkdir(parents=True)
    assert find_project_root(sub) == tmp_path.resolve()
