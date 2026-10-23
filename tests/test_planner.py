from conftest import SAMPLE_LINES
from qwen_voicebake.bake import Baker
from qwen_voicebake.engine.fake import FakeEngine
from qwen_voicebake.ledger import Ledger
from qwen_voicebake.lines_io import load_lines
from qwen_voicebake.planner import plan, route_for
from qwen_voicebake.schema import Line, load_voices
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


def _ids(jobs):
    return [j.line.id for j in jobs]


def test_route_for():
    assert route_for(Line("a", "v", "neutral", "Hi there.")) == "clone"
    assert route_for(Line("a", "v", "neutral", "Hngh", kind="vocal")) == "design"
    assert route_for(Line("a", "v", "neutral", "Hi there.", direction="Far away.")) == "design"


def test_routes_and_refs(bake_project):
    p = _plan(bake_project)
    assert _ids(p.design_jobs) == ["m_grunt", "m_dir"]
    assert _ids(p.clone_jobs) == ["m_hello", "m_angry", "c_hi"]
    assert p.ref_pairs == [("mech", "warm"), ("mech", "anger"), ("clerk", "nervous")]
    grunt = p.design_jobs[0]
    assert grunt.max_new_tokens == bake_project.engine.vocal_max_new_tokens == 48
    assert p.design_jobs[1].max_new_tokens == bake_project.engine.max_new_tokens
    assert all(j.state == "new" for j in p.jobs)


def test_filters(bake_project):
    p = _plan(bake_project, only_voices=["clerk"])
    assert _ids(p.jobs) == ["c_hi"] and p.ref_pairs == [("clerk", "nervous")]
    p = _plan(bake_project, only_lines=["m_*"])
    assert sorted(_ids(p.jobs)) == ["m_angry", "m_dir", "m_grunt", "m_hello"]
    p = _plan(bake_project, only_lines=["m_hello", "c_*"])
    assert sorted(_ids(p.jobs)) == ["c_hi", "m_hello"]


def test_human_and_up_to_date(bake_project):
    Baker(FakeEngine(), bake_project).run(_plan(bake_project))
    p = _plan(bake_project)
    assert p.is_empty() and len(p.up_to_date) == len(SAMPLE_LINES)
    (bake_project.paths.out / "mech" / "m_hello.ogg.human").write_text("")
    p = _plan(bake_project, force=True)
    assert p.skipped_human == ["m_hello"]
    assert "m_hello" not in _ids(p.jobs) and len(p.jobs) == len(SAMPLE_LINES) - 1


def test_force_refs_queues_clone_lines(bake_project):
    Baker(FakeEngine(), bake_project).run(_plan(bake_project))
    p = _plan(bake_project, force_refs=True)
    assert _ids(p.clone_jobs) == ["m_hello", "m_angry", "c_hi"] and not p.design_jobs
