"""Validation tests — these encode DianaLang's safety guarantees. Each 'reject'
test is a program that *should not compile* because it could be unsafe."""
from dianalang.parser import parse
from dianalang.validate import validate, errors_only


def errs(src):
    return errors_only(validate(parse(src)))


def warns(src):
    return [d for d in validate(parse(src)) if d.kind == "warning"]


def test_valid_program_has_no_errors():
    assert errs('skill x { utter "hi" safe run reply_only reply "hey" }') == []


def test_missing_danger_is_rejected():
    e = errs('skill x { utter "x" run reply_only }')
    assert any("danger level" in d.message for d in e)


def test_destructive_in_safe_skill_is_rejected():
    src = 'skill wipe { utter "wipe <p>" arg p : text safe run shell "rm -rf {p}" reply "done" }'
    e = errs(src)
    assert any("rm" in d.message and "safe" in d.message for d in e)


def test_destructive_allowed_when_gated():
    src = 'skill wipe { utter "wipe <p>" arg p : text sudo run shell "rm -rf {p}" reply "done" }'
    assert errs(src) == []


def test_undeclared_interpolation_is_rejected():
    src = 'skill x { utter "x" safe run argv ["echo", "{ghost}"] reply "ok" }'
    e = errs(src)
    assert any("ghost" in d.message for d in e)


def test_undeclared_slot_is_rejected():
    src = 'skill x { utter "say <word>" safe run reply_only reply "ok" }'
    e = errs(src)
    assert any("word" in d.message for d in e)


def test_brace0_in_run_is_rejected():
    src = 'skill x { utter "x" safe run shell "echo {0}" reply "ok" }'
    assert any("{0}" in d.message for d in errs(src))


def test_brace0_in_reply_without_output_is_rejected():
    src = 'skill x { utter "x" safe run reply_only reply "got {0}" }'
    assert any("{0}" in d.message for d in errs(src))


def test_range_on_text_is_rejected():
    src = 'skill x { utter "x <n>" arg n : text range 0..9 safe run argv ["echo", "{n}"] }'
    assert any("range" in d.message for d in errs(src))


def test_enum_on_int_is_rejected():
    src = 'skill x { utter "x <n>" arg n : int in (1, 2) safe run argv ["echo", "{n}"] }'
    assert any("in (...)" in d.message for d in errs(src))


def test_duplicate_skill_name_rejected():
    src = ('skill x { utter "a" safe run reply_only reply "1" }'
           'skill x { utter "b" safe run reply_only reply "2" }')
    assert any("duplicate skill" in d.message for d in errs(src))


def test_no_utter_is_rejected():
    assert any("never fire" in d.message for d in errs('skill x { safe run reply_only reply "x" }'))


def test_unused_arg_is_a_warning_not_error():
    src = 'skill x { utter "x" arg unused : text safe run reply_only reply "ok" }'
    assert errs(src) == []
    assert any("never used" in d.message for d in warns(src))


def test_example_file_compiles_clean():
    import pathlib
    src = (pathlib.Path(__file__).parent.parent / "examples" / "diana.dl").read_text()
    assert errs(src) == []
