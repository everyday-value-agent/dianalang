import pytest

from dianalang import nodes
from dianalang.errors import DianaLangError
from dianalang.parser import parse


def test_parse_minimal_skill():
    prog = parse('skill hi { utter "hi" safe run reply_only reply "hey" }')
    assert len(prog.skills) == 1
    sk = prog.skills[0]
    assert sk.name == "hi"
    assert sk.utters == ["hi"]
    assert sk.danger == "safe"
    assert isinstance(sk.runner, nodes.ReplyOnlyRunner)
    assert sk.reply == "hey"


def test_parse_multiple_utterances():
    prog = parse('skill x { utter "a", "b", "c" safe run reply_only }')
    assert prog.skills[0].utters == ["a", "b", "c"]


def test_parse_arg_with_range():
    prog = parse('skill v { utter "v <n>" arg n : int range 0..100 safe run reply_only }')
    a = prog.skills[0].args[0]
    assert a.name == "n" and a.type == "int"
    assert isinstance(a.constraint, nodes.Range)
    assert (a.constraint.lo, a.constraint.hi) == (0.0, 100.0)


def test_parse_arg_with_enum():
    prog = parse('skill c { utter "c <x>" arg x : word in (red, green, "blue") safe run reply_only }')
    a = prog.skills[0].args[0]
    assert isinstance(a.constraint, nodes.Enum)
    assert a.constraint.choices == ["red", "green", "blue"]


def test_parse_arg_with_maxlen():
    prog = parse('skill t { utter "t <m>" arg m : text max 50 safe run reply_only }')
    assert isinstance(prog.skills[0].args[0].constraint, nodes.MaxLen)
    assert prog.skills[0].args[0].constraint.n == 50


def test_parse_shell_runner():
    prog = parse('skill r { utter "r" sudo run shell "systemctl reboot" reply "ok" }')
    assert isinstance(prog.skills[0].runner, nodes.ShellRunner)
    assert prog.skills[0].runner.template == "systemctl reboot"


def test_parse_argv_runner():
    prog = parse('skill a { utter "a" safe run argv ["wpctl", "set-mute", "toggle"] }')
    assert prog.skills[0].runner.tokens == ["wpctl", "set-mute", "toggle"]


def test_parse_error_has_line():
    with pytest.raises(DianaLangError) as e:
        parse('skill x {\n  utter\n}')      # utter with no string
    # the error points at the offending region (the missing string / stray '}')
    assert e.value.diagnostics[0].line >= 2


def test_missing_danger_leaves_unset():
    prog = parse('skill x { utter "x" run reply_only }')
    assert prog.skills[0].danger == ""       # validator turns this into an error
