import json

from conftest import SAMPLE_LINES, write_lines
from qwen_voicebake.bake import Baker
from qwen_voicebake.engine.fake import FakeEngine
from qwen_voicebake.ledger import Ledger
from qwen_voicebake.lines_io import load_lines
from qwen_voicebake.planner import plan
from qwen_voicebake.refs import ref_path
from qwen_voicebake.schema import load_voices
from qwen_voicebake.tones import load_project_tones


def _plan(project, **kw):
    return plan(
        project,
        load_voices(project.paths.voices),
        load_lines(project),
        load_project_tones(project),
        Ledger.for_root(project.root),
        **kw,
    )


def _bake(project, engine=None, **kw):
    engine = engine or FakeEngine()
    events = []
    s = Baker(engine, project, on_event=events.append).run(_plan(project, **kw))
    return s, engine, events


def test_full_bake_then_noop(bake_project):
    s, e, events = _bake(bake_project)
    assert sorted(s.baked) == sorted(d["id"] for d in SAMPLE_LINES) and not s.failed
    out = bake_project.paths.out
    assert (out / "mech" / "m_hello.ogg").is_file() and (out / "clerk" / "c_hi.ogg").is_file()
    assert len(s.refs_made) == 3
    takes = [ev for ev in events if ev["type"] == "take"]
    assert {ev["route"] for ev in takes} == {"design", "clone"}
    assert events[-1]["type"] == "done"

    s2, e2, _ = _bake(bake_project)
    assert s2.baked == [] and e2.calls == [] and len(s2.up_to_date) == len(SAMPLE_LINES)


def test_design_before_clone_minimal_swaps(bake_project):
    _, e, _ = _bake(bake_project)
    ops = [op for op, _ in e.calls]
    first_clone = ops.index("clone")
    assert all(op == "design" for op in ops[:first_clone])
    assert all(op == "clone" for op in ops[first_clone:])
    assert ops.count("design") == 3 + 2  # three refs, two design takes
    assert e.swaps == 1


def test_editing_one_line_rebakes_one(bake_project):
    _bake(bake_project)
    lines = [dict(d) for d in SAMPLE_LINES]
    lines[0]["text"] = "Back again, are you? Good."
    write_lines(bake_project.root, lines)
    s, e, _ = _bake(bake_project)
    assert s.baked == ["m_hello"] and e.calls == [("clone", e.clone_model)]


def test_changing_ref_audio_rebakes_its_lines(bake_project):
    _bake(bake_project)
    rp = ref_path(bake_project, "mech", "warm")
    other = ref_path(bake_project, "mech", "anger")
    rp.write_bytes(other.read_bytes())
    s, e, _ = _bake(bake_project)
    assert s.baked == ["m_hello"]
    assert all(op == "clone" for op, _ in e.calls)


def test_hard_qa_rejected_not_stamped(bake_project):
    text = SAMPLE_LINES[0]["text"]
    s, _, events = _bake(bake_project, FakeEngine(fail={text: "runaway"}))
    assert s.failed == ["m_hello"]
    out = bake_project.paths.out
    assert not (out / "mech" / "m_hello.ogg").exists()
    assert (bake_project.state_dir / "rejected" / "mech" / "m_hello.ogg").is_file()
    led = Ledger.for_root(bake_project.root)
    assert "mech/m_hello.ogg" not in led.takes and "runaway" in led.failed["mech/m_hello.ogg"]
    ev = next(ev for ev in events if ev["type"] == "take" and ev["line_id"] == "m_hello")
    assert ev["ok"] is False and ev["qa"] == "hard"
    # a later good bake retries and clears the failure
    s2, _, _ = _bake(bake_project)
    assert s2.baked == ["m_hello"]
    assert "mech/m_hello.ogg" not in Ledger.for_root(bake_project.root).failed


def test_empty_failure_never_writes(bake_project):
    text = SAMPLE_LINES[4]["text"]
    s, _, _ = _bake(bake_project, FakeEngine(fail={text: "empty"}))
    assert s.failed == ["c_hi"]
    assert not (bake_project.paths.out / "clerk" / "c_hi.ogg").exists()
    assert not (bake_project.state_dir / "rejected" / "clerk" / "c_hi.ogg").exists()


def test_manifest(bake_project):
    text = SAMPLE_LINES[4]["text"]
    _bake(bake_project, FakeEngine(fail={text: "empty"}))
    m = json.loads((bake_project.paths.out / "manifest.json").read_text(encoding="utf-8"))
    assert m["version"] == 1 and m["format"] == "ogg"
    assert set(m["voices"]) == {"mech"}
    hello = m["voices"]["mech"]["m_hello"]
    assert hello["path"] == "mech/m_hello.ogg" and hello["route"] == "clone"
    assert hello["tone"] == "warm" and hello["text"] == SAMPLE_LINES[0]["text"]
    assert hello["duration"] > 0
    assert m["voices"]["mech"]["m_grunt"]["route"] == "design"


def test_dry_run_and_limit(bake_project):
    events = []
    s = Baker(None, bake_project, on_event=events.append).run(_plan(bake_project), dry_run=True)
    assert s.dry_run and s.planned == len(SAMPLE_LINES)
    assert not bake_project.paths.out.exists()
    s = Baker(FakeEngine(), bake_project).run(_plan(bake_project), limit=2)
    assert len(s.baked) == 2


def test_cancel(bake_project):
    s = Baker(FakeEngine(), bake_project).run(_plan(bake_project), cancel=lambda: True)
    assert s.cancelled and s.baked == []


def test_regenerate_single_line(bake_project):
    _bake(bake_project)
    led = Ledger.for_root(bake_project.root)
    old_ts = led.takes["mech/m_hello.ogg"]["ts"]
    e = FakeEngine()
    res = Baker(e, bake_project).regenerate("m_hello", seed=99)
    assert res.ok and res.route == "clone" and res.rel == "mech/m_hello.ogg"
    assert e.calls == [("clone", e.clone_model)]
    assert Ledger.for_root(bake_project.root).takes["mech/m_hello.ogg"]["ts"] >= old_ts
    # still current: a normal bake does not overwrite the regenerated take
    s, e2, _ = _bake(bake_project)
    assert e2.calls == []


def test_regenerate_designs_missing_ref(bake_project):
    e = FakeEngine()
    res = Baker(e, bake_project).regenerate("c_hi")
    assert res.ok
    assert [op for op, _ in e.calls] == ["design", "clone"]


def test_regenerate_refuses_human_take(bake_project):
    _bake(bake_project)
    take = bake_project.paths.out / "mech" / "m_hello.ogg"
    take.write_bytes(b"human audio")
    (bake_project.paths.out / "mech" / "m_hello.ogg.human").write_text("")
    e = FakeEngine()
    res = Baker(e, bake_project).regenerate("m_hello")
    assert not res.ok and "human" in res.error
    assert take.read_bytes() == b"human audio" and e.calls == []


def test_regenerate_records_seed(bake_project):
    Baker(FakeEngine(), bake_project).regenerate("m_grunt", seed=99)
    assert Ledger.for_root(bake_project.root).takes["mech/m_grunt.ogg"]["seed"] == 99


def test_failed_ref_does_not_stop_bake(bake_project):
    # clerk's reference text comes back empty: its ref fails, everything else bakes
    s, _, events = _bake(bake_project, FakeEngine(fail={"Good morning to you.": "empty"}))
    assert s.failed == ["c_hi"]
    assert sorted(s.baked) == ["m_angry", "m_dir", "m_grunt", "m_hello"]
    warn = [ev for ev in events if ev["type"] == "warn" and ev.get("failed")]
    assert [(w["voice"], w["tone"]) for w in warn] == [("clerk", "nervous")]
    take = next(ev for ev in events if ev["type"] == "take" and ev["line_id"] == "c_hi")
    assert take["error"] == "reference missing"
    assert not ref_path(bake_project, "clerk", "nervous").exists()


def test_hard_qa_ref_rejected(bake_project):
    s, _, _ = _bake(bake_project, FakeEngine(fail={"Good morning to you.": "runaway"}))
    assert s.failed == ["c_hi"]
    assert not ref_path(bake_project, "clerk", "nervous").exists()
    assert (bake_project.state_dir / "rejected" / "refs" / "clerk" / "nervous.ogg").is_file()


def test_engine_exception_in_ref_is_contained(bake_project):
    class Boom(FakeEngine):
        def design(self, text, *a, **k):
            if text == "Good morning to you.":
                raise RuntimeError("out of memory")
            return super().design(text, *a, **k)

    s, _, _ = _bake(bake_project, Boom())
    assert s.failed == ["c_hi"] and len(s.baked) == 4


def test_clone_prompt_cache_cleared_on_model_change(bake_project):
    class Counting(FakeEngine):
        prompts = 0

        def make_clone_prompt(self, *a):
            Counting.prompts += 1
            return super().make_clone_prompt(*a)

    _bake(bake_project)
    lines = [dict(d) for d in SAMPLE_LINES]
    lines[0]["text"] = "Changed one."
    lines[0]["tone"] = "anger"
    lines[1]["text"] = "Changed two."
    write_lines(bake_project.root, lines)
    e = Counting()
    baker = Baker(e, bake_project)
    baker.run(_plan(bake_project))
    assert Counting.prompts == 1  # same ref, same loaded model: reused
    e.load("other-model")
    lines[0]["text"] = "Changed three."
    write_lines(bake_project.root, lines)
    baker.run(_plan(bake_project))
    assert Counting.prompts == 2


def _escape_project(project_dir):
    voices = {
        "version": 1,
        "voices": {
            "mech": {"instruct": "A gruff man.", "ref_text": "Hello there friend."},
            "..": {"instruct": "Sneaky.", "ref_text": "Hello there friend."},
            ".": {"instruct": "Sneaky.", "ref_text": "Hello there friend."},
        },
    }
    (project_dir / "voices.json").write_text(json.dumps(voices), encoding="utf-8")
    write_lines(
        project_dir,
        [
            {"id": "ok_line", "voice": "mech", "tone": "warm", "text": "Back again, are you?"},
            {"id": "up_clone", "voice": "..", "tone": "warm", "text": "Out we go now."},
            {"id": "up_vocal", "voice": "..", "tone": "neutral", "text": "Hah!", "kind": "vocal"},
            {"id": "here", "voice": ".", "tone": "warm", "text": "Right next to it."},
        ],
    )
    from qwen_voicebake.config import load_project

    return load_project(project_dir)


def _stray_audio(project, root):
    """Audio files under root that are not in the output, refs or state folders."""
    allowed = [project.paths.out.resolve(), project.paths.refs.resolve(), project.state_dir]
    return [
        p
        for p in root.rglob("*.ogg")
        if not any(p.resolve().is_relative_to(a.resolve()) for a in allowed)
    ]


def test_run_refuses_paths_outside_out(project_dir):
    project = _escape_project(project_dir)
    s, _, events = _bake(project)
    assert s.baked == ["ok_line"]
    assert sorted(s.failed) == ["here", "up_clone", "up_vocal"]
    errors = {ev["line_id"]: ev["error"] for ev in events if ev["type"] == "take" and not ev["ok"]}
    assert all("outside" in e or "invalid" in e for e in errors.values())
    assert _stray_audio(project, project_dir) == []
    assert list(project_dir.parent.glob("*.ogg")) == []
    assert not (project_dir / "up_clone.ogg").exists()
    assert not (project.paths.out / "here.ogg").exists()
    # no reference was designed for the escaping voices either
    assert not any(p.name == "warm.ogg" and p.parent.name != "mech" for p in project_dir.rglob("*"))


def test_regenerate_refuses_paths_outside_out(project_dir):
    project = _escape_project(project_dir)
    engine = FakeEngine()
    res = Baker(engine, project).regenerate("up_clone")
    assert not res.ok and "outside" in res.error
    assert engine.calls == []
    assert not (project_dir / "up_clone.ogg").exists()
    assert Baker(engine, project).regenerate("ok_line").ok
