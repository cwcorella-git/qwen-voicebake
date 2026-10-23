import dataclasses
from pathlib import Path

from qwen_voicebake.config import EngineCfg, PathsCfg
from qwen_voicebake.hashing import ref_inputs_hash, stable_hash, take_inputs_hash
from qwen_voicebake.schema import Line, Voice

V = Voice("mech", "A man.", "Hello.", seed=1)
L = Line("a", "mech", "warm", "Back again?")
E = EngineCfg()
P = PathsCfg(Path("v"), Path("l"), None, Path("t"), Path("r"), Path("o"))


def take(line=L, voice=V, tone=" t", route="clone", sha="abc", e=E, p=P):
    return take_inputs_hash(line, voice, tone, route, sha, e, p)


def test_stable_hash():
    assert stable_hash({"a": 1, "b": 2}) == stable_hash({"b": 2, "a": 1})
    assert stable_hash([1]) != stable_hash([2])
    assert take() == take()


def test_ref_hash_changes():
    base = ref_inputs_hash(V, "warm", " t", E)
    assert base == ref_inputs_hash(V, "warm", " t", E)
    assert base != ref_inputs_hash(dataclasses.replace(V, ref_text="x"), "warm", " t", E)
    assert base != ref_inputs_hash(dataclasses.replace(V, instruct="x"), "warm", " t", E)
    assert base != ref_inputs_hash(dataclasses.replace(V, seed=2), "warm", " t", E)
    assert base != ref_inputs_hash(V, "warm", " u", E)
    assert base != ref_inputs_hash(V, "cold", " t", E)
    assert base != ref_inputs_hash(V, "warm", " t", dataclasses.replace(E, design_model="m"))


def test_clone_hash_changes():
    base = take()
    assert base != take(line=dataclasses.replace(L, text="x"))
    assert base != take(voice=dataclasses.replace(V, instruct="x"))
    assert base != take(tone=" u")
    assert base != take(sha="def")
    assert base != take(e=dataclasses.replace(E, clone_model="m"))
    assert base != take(voice=dataclasses.replace(V, temperature=0.9))
    assert base != take(voice=dataclasses.replace(V, language="German"))
    assert base != take(p=dataclasses.replace(P, format="wav"))
    assert base != take(p=dataclasses.replace(P, normalize=True))
    assert base == take(voice=dataclasses.replace(V, seed=99))  # seed unused by clone
    assert base == take(line=dataclasses.replace(L, direction="x"))  # direction unused


def test_design_hash_changes():
    d = take(route="design")
    assert d != take()
    assert d != take(route="design", line=dataclasses.replace(L, direction="slow"))
    assert d != take(route="design", voice=dataclasses.replace(V, seed=2))
    assert d != take(route="design", e=dataclasses.replace(E, design_model="m"))
    assert d != take(route="design", e=dataclasses.replace(E, max_new_tokens=100))
    assert d != take(route="design", line=dataclasses.replace(L, kind="vocal"))
    assert d == take(route="design", sha="zzz")  # ref audio unused by design
