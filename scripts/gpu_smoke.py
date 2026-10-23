"""Manual GPU smoke test (not run in CI).

Loads the design model, designs one line, clones a second line from it, writes two files
and prints timings. Needs the [tts] extra and a GPU (or patience on cpu).

    python scripts/gpu_smoke.py [OUT_DIR] [--clone-model Qwen/Qwen3-TTS-12Hz-0.6B-Base]
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from qwen_voicebake.config import EngineCfg
from qwen_voicebake.engine.qwen import QwenEngine
from qwen_voicebake.post import postprocess, write_audio

INSTRUCT = "A calm middle-aged woman with a clear, warm voice, speaking evenly."
REF_TEXT = "The weather turned cold overnight, so we kept the fire going until morning."
LINE = "If you need anything else, you know where to find me."


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="?", default="smoke_out")
    ap.add_argument("--clone-model", default=EngineCfg().clone_model)
    ap.add_argument("--device", default="auto")
    args = ap.parse_args()
    out = Path(args.out)

    t = time.monotonic()
    eng = QwenEngine(EngineCfg(clone_model=args.clone_model, device=args.device))
    print(f"device: {eng.device_info()}  ({time.monotonic() - t:.1f} s incl. torch import)")

    t = time.monotonic()
    eng.load(eng.design_model)
    print(f"load design model: {time.monotonic() - t:.1f} s")

    t = time.monotonic()
    ref = eng.design(REF_TEXT, INSTRUCT, "English", 1234, 0.5, 2048)
    ref_wav = postprocess(ref.wav, ref.sr)
    write_audio(out / "ref.ogg", ref_wav, ref.sr, "ogg")
    print(f"design: {time.monotonic() - t:.1f} s -> {len(ref_wav) / ref.sr:.2f} s audio")

    t = time.monotonic()
    prompt = eng.make_clone_prompt(ref_wav, ref.sr, REF_TEXT)
    print(f"swap + clone prompt: {time.monotonic() - t:.1f} s")

    for i in range(2):
        t = time.monotonic()
        take = eng.clone(LINE, "English", prompt, 1234, 0.5, 2048)
        wav = postprocess(take.wav, take.sr)
        print(f"clone #{i + 1}: {time.monotonic() - t:.1f} s -> {len(wav) / take.sr:.2f} s audio")
    write_audio(out / "line.ogg", wav, take.sr, "ogg")
    print(f"wrote {out / 'ref.ogg'} and {out / 'line.ogg'}")


if __name__ == "__main__":
    main()
