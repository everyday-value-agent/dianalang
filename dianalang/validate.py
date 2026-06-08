"""Semantic validation — where DianaLang's safety guarantees are enforced.

The language is designed so that an *invalid* program is one that could be
unsafe. A program that passes validation has, by construction:

  1. an explicit danger level on every skill (no accidental 'safe' default);
  2. no destructive command sitting in a 'safe' skill;
  3. every shell/argv/reply interpolation bound to a *declared, typed* argument
     — so the runtime can sanitize it (injection becomes impossible);
  4. every capture slot in an utterance bound to a declared argument;
  5. constraints that match their argument's type.

Returns a list of Diagnostics; an empty list means the program is safe to run.
"""
from __future__ import annotations

import re

from . import nodes
from .errors import Diagnostic

_PLACEHOLDER = re.compile(r"\{([^}]*)\}")
_SLOT = re.compile(r"<([^>]*)>")
_DANGERS = {"safe", "confirm", "sudo"}

# Binaries/operators that should never live in a 'safe' skill, even fully quoted —
# quoting stops injection, but `rm -rf {dir}` is destructive by the author's intent.
_DESTRUCTIVE = {
    "rm", "rmdir", "mkfs", "dd", "shutdown", "reboot", "poweroff", "halt",
    "shred", "fdisk", "parted", "kill", "pkill", "killall", "chmod", "chown",
    "mv", "truncate",
}
_FORKBOMB = re.compile(r":\s*\(\s*\)\s*\{")


def _placeholders(template: str) -> list[str]:
    return [m.group(1).strip() for m in _PLACEHOLDER.finditer(template or "")]


def _slots(pattern: str) -> list[str]:
    return [m.group(1).strip() for m in _SLOT.finditer(pattern or "")]


def _runner_template_strings(runner) -> list[str]:
    if isinstance(runner, nodes.ShellRunner):
        return [runner.template]
    if isinstance(runner, nodes.ArgvRunner):
        return list(runner.tokens)
    if isinstance(runner, nodes.ReadRunner):
        return [runner.path_template]
    return []


def _runner_produces_stdout(runner) -> bool:
    return isinstance(runner, (nodes.ShellRunner, nodes.ArgvRunner, nodes.ReadRunner))


def _has_destructive(template: str) -> str | None:
    if _FORKBOMB.search(template):
        return ":(){ fork bomb"
    for word in re.findall(r"[A-Za-z_][\w./-]*", template):
        base = word.rsplit("/", 1)[-1]
        if base in _DESTRUCTIVE:
            return base
    return None


def validate(program: nodes.Program) -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    seen_skills: dict[str, int] = {}
    utter_owner: dict[str, str] = {}

    for sk in program.skills:
        if sk.name in seen_skills:
            diags.append(Diagnostic(sk.line, f"duplicate skill name {sk.name!r}"))
        seen_skills[sk.name] = sk.line

        # danger must be explicit
        if sk.danger not in _DANGERS:
            diags.append(Diagnostic(
                sk.line,
                f"skill {sk.name!r} must declare a danger level (safe/confirm/sudo)"))

        # must be matchable + executable
        if not sk.utters:
            diags.append(Diagnostic(sk.line, f"skill {sk.name!r} has no 'utter' pattern — it can never fire"))
        if sk.runner is None:
            diags.append(Diagnostic(sk.line, f"skill {sk.name!r} has no 'run' clause"))

        # unique arg names + constraint/type agreement
        seen_args: set[str] = set()
        for a in sk.args:
            if a.name in seen_args:
                diags.append(Diagnostic(a.line, f"duplicate arg {a.name!r} in skill {sk.name!r}"))
            seen_args.add(a.name)
            _check_constraint(a, sk, diags)

        declared = {a.name for a in sk.args}
        used: set[str] = set()

        # utter slots must reference declared args
        for pat in sk.utters:
            if pat in utter_owner and utter_owner[pat] != sk.name:
                diags.append(Diagnostic(sk.line, f"utterance {pat!r} is also handled by "
                                                 f"{utter_owner[pat]!r} (ambiguous)", kind="warning"))
            utter_owner.setdefault(pat, sk.name)
            for slot in _slots(pat):
                if slot not in declared:
                    diags.append(Diagnostic(sk.line, f"utterance slot <{slot}> in {sk.name!r} "
                                                     f"has no matching 'arg {slot}'"))
                else:
                    used.add(slot)

        # template placeholders must reference declared args (or {0} = runner stdout)
        for tmpl in _runner_template_strings(sk.runner):
            for ph in _placeholders(tmpl):
                if ph == "0":
                    diags.append(Diagnostic(sk.line, f"{{0}} (command output) is only valid in 'reply', "
                                                     f"not in 'run' — skill {sk.name!r}"))
                elif ph not in declared:
                    diags.append(Diagnostic(sk.line, f"interpolation {{{ph}}} in skill {sk.name!r} "
                                                     f"has no matching 'arg {ph}'"))
                else:
                    used.add(ph)

        if sk.reply is not None:
            for ph in _placeholders(sk.reply):
                if ph == "0":
                    if not _runner_produces_stdout(sk.runner):
                        diags.append(Diagnostic(sk.line, f"reply uses {{0}} but skill {sk.name!r}'s runner "
                                                         f"produces no output"))
                elif ph not in declared:
                    diags.append(Diagnostic(sk.line, f"reply interpolation {{{ph}}} in {sk.name!r} "
                                                     f"has no matching 'arg {ph}'"))
                else:
                    used.add(ph)

        # the core safety rule: destructive shell/argv in a 'safe' skill
        if sk.danger == "safe" and sk.runner is not None:
            for tmpl in _runner_template_strings(sk.runner):
                hit = _has_destructive(tmpl)
                if hit:
                    diags.append(Diagnostic(sk.line, f"skill {sk.name!r} is 'safe' but its command uses "
                                                     f"{hit!r} — mark it 'confirm' or 'sudo'"))

        for a in sk.args:
            if a.name not in used:
                diags.append(Diagnostic(a.line, f"arg {a.name!r} in {sk.name!r} is never used "
                                                f"(no slot or interpolation)", kind="warning"))

    return diags


def _check_constraint(a: nodes.Arg, sk: nodes.Skill, diags: list[Diagnostic]) -> None:
    c = a.constraint
    if c is None:
        return
    if isinstance(c, nodes.Range):
        if a.type not in ("int", "number"):
            diags.append(Diagnostic(a.line, f"'range' constraint on {a.name!r} requires an int/number arg"))
        if c.lo > c.hi:
            diags.append(Diagnostic(a.line, f"range on {a.name!r} is inverted ({c.lo}..{c.hi})"))
    elif isinstance(c, nodes.Enum):
        if a.type not in ("word", "text"):
            diags.append(Diagnostic(a.line, f"'in (...)' constraint on {a.name!r} requires a word/text arg"))
        if not c.choices:
            diags.append(Diagnostic(a.line, f"empty 'in (...)' set on {a.name!r}"))
    elif isinstance(c, nodes.MaxLen):
        if a.type not in ("word", "text"):
            diags.append(Diagnostic(a.line, f"'max' constraint on {a.name!r} requires a word/text arg"))


def errors_only(diags: list[Diagnostic]) -> list[Diagnostic]:
    return [d for d in diags if d.kind == "error"]
