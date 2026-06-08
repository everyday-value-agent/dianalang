import pytest

from dianalang.errors import DianaLangError
from dianalang.lexer import tokenize


def kinds(src):
    return [t.kind for t in tokenize(src)]


def test_basic_tokens():
    toks = tokenize('skill battery { safe }')
    assert [t.kind for t in toks] == ["skill", "IDENT", "LBRACE", "safe", "RBRACE", "EOF"]


def test_string_with_escapes():
    toks = tokenize(r'reply "hi \"there\"\n"')
    assert toks[0].kind == "reply"
    assert toks[1].kind == "STRING"
    assert toks[1].value == 'hi "there"\n'


def test_numbers_and_range():
    assert kinds("range 0..100") == ["range", "NUMBER", "RANGE", "NUMBER", "EOF"]
    nums = [t.value for t in tokenize("range 0..100") if t.kind == "NUMBER"]
    assert nums == ["0", "100"]


def test_float_number():
    toks = tokenize("max 1.5")
    assert toks[1].value == "1.5"


def test_comments_skipped():
    assert kinds("# a comment\nskill x { safe }") == [
        "skill", "IDENT", "LBRACE", "safe", "RBRACE", "EOF"]


def test_line_tracking():
    toks = tokenize("skill\n\nbattery")
    assert toks[0].line == 1
    assert toks[1].line == 3


def test_unterminated_string_errors():
    with pytest.raises(DianaLangError) as e:
        tokenize('reply "oops')
    assert "unterminated" in str(e.value)


def test_unexpected_char_errors():
    with pytest.raises(DianaLangError):
        tokenize("skill ? {}")
