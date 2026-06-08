"""DianaLang — a tiny declarative language for voice-assistant skills where
safety is a language feature: you cannot express an injection-prone or
accidentally-ungated skill. A valid program is a safe program.

    from dianalang import compile_source, match, execute

    program = compile_source(open("diana.dl").read())   # parse + validate
    m = match(program, "set volume to 40")
    result = execute(m, gate=lambda sk: ask_user(sk))
    print(result.reply)
"""
from __future__ import annotations

from .errors import Diagnostic, DianaLangError
from .nodes import Program, Skill, Arg
from .parser import parse
from .validate import validate, errors_only
from .runtime import match, execute, Match, ExecResult, NeedsAuthorization, CoercionError

__version__ = "0.1.0"

__all__ = [
    "parse", "validate", "errors_only", "compile_source",
    "match", "execute", "Match", "ExecResult",
    "NeedsAuthorization", "CoercionError",
    "Program", "Skill", "Arg", "Diagnostic", "DianaLangError",
]


def compile_source(src: str) -> Program:
    """Parse and validate DianaLang source. Raises DianaLangError on any error
    diagnostic; returns the Program (warnings are allowed through)."""
    program = parse(src)
    errs = errors_only(validate(program))
    if errs:
        raise DianaLangError(errs)
    return program
