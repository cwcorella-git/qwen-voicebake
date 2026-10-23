from qwen_voicebake import refs
from qwen_voicebake.engine.fake import FakeEngine
from qwen_voicebake.hashing import sha1_file
from qwen_voicebake.schema import load_voices, save_voices


def _status(project, voice, tone="warm"):
    from qwen_voicebake.tones import load_project_tones

    v = load_voices(project.paths.voices)[voice]
    return refs.ref_status(project, v, tone, load_project_tones(project)[tone])


def test_missing_auto_designed_then_ok(bake_project):
    e = FakeEngine()
    assert _status(bake_project, "mech") == "missing"
    made = refs.ensure_refs(e, bake_project, [("mech", "warm")])
    assert made == [("mech", "warm")]
    assert refs.ref_path(bake_project, "mech", "warm").is_file()
    assert _status(bake_project, "mech") == "ok"
    assert refs.ensure_refs(e, bake_project, [("mech", "warm")]) == []
    assert refs.ensure_refs(e, bake_project, [("mech", "warm")], force=True) == [("mech", "warm")]


def test_stale_when_persona_changes(bake_project):
    e = FakeEngine()
    refs.ensure_refs(e, bake_project, [("mech", "warm")])
    voices = load_voices(bake_project.paths.voices)
    voices["mech"].instruct = "A different man."
    save_voices(bake_project.paths.voices, voices)
    assert _status(bake_project, "mech") == "stale"
    assert refs.ensure_refs(e, bake_project, [("mech", "warm")]) == [("mech", "warm")]


def test_pinned_never_regenerated(bake_project):
    e = FakeEngine()
    refs.ensure_refs(e, bake_project, [("mech", "warm")])
    refs.set_pinned(bake_project, "mech", "warm", True)
    assert _status(bake_project, "mech") == "pinned"
    before = sha1_file(refs.ref_path(bake_project, "mech", "warm"))
    assert refs.ensure_refs(e, bake_project, [("mech", "warm")], force=True) == []
    voices = load_voices(bake_project.paths.voices)
    voices["mech"].instruct = "A different man."
    save_voices(bake_project.paths.voices, voices)
    assert _status(bake_project, "mech") == "pinned-stale"
    events = []
    assert refs.ensure_refs(e, bake_project, [("mech", "warm")], on_event=events.append) == []
    assert events and events[0]["type"] == "warn"
    assert sha1_file(refs.ref_path(bake_project, "mech", "warm")) == before
    refs.set_pinned(bake_project, "mech", "warm", False)
    assert _status(bake_project, "mech") == "stale"


def test_candidates_and_pick(bake_project):
    e = FakeEngine()
    paths = refs.gen_candidates(e, bake_project, "mech", "warm", n=3)
    assert [p.name for p in paths] == ["seed7.ogg", "seed8.ogg", "seed9.ogg"]
    assert all(p.is_file() for p in paths)
    assert paths[0].parent == bake_project.state_dir / "candidates" / "mech" / "warm"
    explicit = refs.gen_candidates(e, bake_project, "mech", "warm", seeds=[42])
    assert explicit[0].name == "seed42.ogg"
    dst = refs.pick_candidate(bake_project, "mech", "warm", 42)
    assert sha1_file(dst) == sha1_file(explicit[0])
    entry = refs.load_lock(bake_project)["mech/warm"]
    assert entry["seed"] == 42 and entry["pinned"] is True
    assert entry["audio_sha1"] == sha1_file(dst)
    assert _status(bake_project, "mech") == "pinned"
