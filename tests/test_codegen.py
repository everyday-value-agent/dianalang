"""Codegen produces a standalone importable module whose behaviour matches the
in-memory interpreter."""
import importlib.util
import pathlib

from dianalang import compile_source, codegen, match


SRC = '''
skill set_volume {
    utter "set volume to <level>", "volume <level>"
    arg level : int range 0..150
    safe
    run argv ["wpctl", "set-volume", "{level}%"]
    reply "Volume set to {level} percent."
}
skill greeting {
    utter "hello"
    safe
    run reply_only
    reply "Hey."
}
'''


def _load_module(path):
    spec = importlib.util.spec_from_file_location("compiled_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_generated_module_matches_interpreter(tmp_path):
    program = compile_source(SRC)
    code = codegen.generate(program, source="t.dl", out="t.py")
    out = tmp_path / "compiled_test.py"
    out.write_text(code)

    mod = _load_module(str(out))
    # same skills compiled in
    assert [s.name for s in mod.PROGRAM.skills] == [s.name for s in program.skills]
    # match agrees
    m1 = match(program, "set volume to 25")
    m2 = mod.match("set volume to 25")
    assert m1.skill.name == m2.skill.name == "set_volume"
    assert m1.args == m2.args == {"level": 25}


def test_generated_dispatch_runs(tmp_path):
    program = compile_source(SRC)
    out = tmp_path / "compiled_test2.py"
    out.write_text(codegen.generate(program))
    mod = _load_module(str(out))
    res = mod.dispatch("hello")
    assert res.reply == "Hey."
    assert mod.dispatch("nonsense utterance") is None


def test_generated_module_is_valid_python(tmp_path):
    code = codegen.generate(compile_source(SRC))
    compile(code, "compiled.py", "exec")     # raises SyntaxError if malformed
