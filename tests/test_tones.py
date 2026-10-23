from qwen_voicebake.schema import Voice
from qwen_voicebake.tones import BUILTIN_TONES, instruct_for, load_project_tones

FIRST_15 = [
    "neutral",
    "seeking",
    "trust",
    "guilt",
    "fear",
    "anger",
    "empathy",
    "assertion",
    "cold",
    "opposition",
    "curiosity",
    "warm",
    "disgust",
    "elation",
    "suffering",
]


def test_builtin_count_and_first_15():
    assert len(BUILTIN_TONES) == 48
    assert list(BUILTIN_TONES)[:15] == FIRST_15
    assert BUILTIN_TONES["neutral"] == ""
    for name, text in BUILTIN_TONES.items():
        if name != "neutral":
            assert text.startswith(" Right now: ")


def test_no_toml_returns_builtins(project):
    assert load_project_tones(project) == BUILTIN_TONES


def test_overrides_merge(project):
    project.paths.tones.write_text(
        '[tones]\ngrumpy = "Right now: irritable."\ncold = "icy"\nblank = ""\n'
    )
    t = load_project_tones(project)
    assert t["grumpy"] == " Right now: irritable."
    assert t["cold"] == " icy"
    assert t["blank"] == ""
    assert t["warm"] == BUILTIN_TONES["warm"]
    assert len(t) == 50


def test_instruct_composition():
    v = Voice("v", "A man.", "x")
    assert instruct_for(v, "") == "A man."
    assert instruct_for(v, " Right now: calm.") == "A man. Right now: calm."
    assert instruct_for(v, " Right now: calm.", "slowly") == "A man. Right now: calm. slowly"
