import subprocess
import sys
import textwrap


def test_engine_qwen_module_does_not_import_torch():
    code = "import sys, qwen_voicebake.engine.qwen; assert 'torch' not in sys.modules"
    subprocess.run([sys.executable, "-c", code], check=True)


def test_fake_bake_without_torch(bake_project):
    code = textwrap.dedent(
        f"""
        import sys
        from qwen_voicebake import bake, check, planner
        from qwen_voicebake.config import load_project
        from qwen_voicebake.engine import get_engine
        from qwen_voicebake.ledger import Ledger
        from qwen_voicebake.lines_io import load_lines
        from qwen_voicebake.schema import load_voices
        from qwen_voicebake.tones import load_project_tones

        p = load_project({str(bake_project.root)!r})
        check.run_check(p)
        plan = planner.plan(p, load_voices(p.paths.voices), load_lines(p),
                            load_project_tones(p), Ledger.for_root(p.root))
        bake.Baker(None, p).run(plan, dry_run=True)
        s = bake.Baker(get_engine(p, fake=True), p).run(plan)
        assert s.baked and not s.failed, s
        assert "torch" not in sys.modules
        """
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_to_mono_channel_axis():
    import numpy as np

    from qwen_voicebake.engine.qwen import _to_mono

    stereo_cf = np.stack([np.ones(100), np.zeros(100)])  # (2, n)
    stereo_cl = stereo_cf.T  # (n, 2)
    for arr in (stereo_cf, stereo_cl):
        out = _to_mono(arr)
        assert out.shape == (100,) and np.allclose(out, 0.5)
    assert _to_mono(np.ones((1, 50))).shape == (50,)
