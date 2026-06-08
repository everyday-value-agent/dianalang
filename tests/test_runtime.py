import pytest

from dianalang import compile_source
from dianalang.runtime import NeedsAuthorization, execute, match


PROG = compile_source('''
skill set_volume {
    utter "set volume to <level>", "volume <level>"
    arg level : int range 0..150
    safe
    run argv ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "{level}%"]
    reply "Volume set to {level} percent."
}
skill greeting {
    utter "hello", "hi there"
    safe
    run reply_only
    reply "Hey Thanu."
}
skill reboot {
    utter "reboot"
    sudo
    run shell "systemctl reboot"
    reply "Rebooting."
}
skill color {
    utter "set color to <c>"
    arg c : word in (red, green, blue)
    safe
    run argv ["set-color", "{c}"]
    reply "Color {c}."
}
''')


def test_match_and_extract_int_arg():
    m = match(PROG, "set volume to 40")
    assert m.skill.name == "set_volume"
    assert m.args == {"level": 40}


def test_phrase_match_no_args():
    assert match(PROG, "hello").skill.name == "greeting"
    assert match(PROG, "well, hi there!").skill.name == "greeting"


def test_no_match_returns_none():
    assert match(PROG, "what is the meaning of life") is None


def test_out_of_range_does_not_match():
    # 999 is out of 0..150 → coercion fails → that skill is rejected
    assert match(PROG, "set volume to 999") is None


def test_non_numeric_does_not_match_int_slot():
    assert match(PROG, "set volume to loud") is None


def test_enum_rejects_unknown_value():
    assert match(PROG, "set color to teal") is None
    assert match(PROG, "set color to RED").args == {"c": "red"}   # case-normalized to declared form


def test_argv_render_dry_run():
    m = match(PROG, "set volume to 30")
    res = execute(m, dry_run=True)
    assert res.command == ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "30%"]
    assert res.reply == "Volume set to 30 percent."


def test_reply_only_executes_without_command():
    m = match(PROG, "hello")
    res = execute(m)
    assert res.reply == "Hey Thanu."
    assert res.command is None


def test_sudo_skill_refused_without_gate():
    m = match(PROG, "reboot")
    with pytest.raises(NeedsAuthorization):
        execute(m, dry_run=True)


def test_sudo_skill_runs_with_gate():
    m = match(PROG, "reboot")
    res = execute(m, gate=lambda sk: True, dry_run=True)
    assert res.command == "systemctl reboot"


def test_gate_returning_false_refuses():
    m = match(PROG, "reboot")
    with pytest.raises(NeedsAuthorization):
        execute(m, gate=lambda sk: False, dry_run=True)


def test_specificity_prefers_anchored_over_phrase():
    prog = compile_source('''
        skill a { utter "open settings" safe run reply_only reply "A" }
        skill b { utter "open <x>" arg x : word safe run argv ["xdg-open", "{x}"] reply "B" }
    ''')
    # "open settings" should hit the exact skill, not the generic slot skill
    assert match(prog, "open settings").skill.name == "a"
    assert match(prog, "open spotify").skill.name == "b"
