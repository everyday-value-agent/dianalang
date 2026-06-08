"""Runtime: match an utterance to a skill + typed args, then execute it safely.

Two guarantees the executor upholds no matter what the utterance contains:

  * **No injection.** Shell interpolations are `shlex.quote`d; argv interpolations
    become single argv elements. A captured value like ``'$(reboot)`` is data,
    never code.
  * **Gate at the choke point.** A 'confirm'/'sudo' skill will not run unless the
    caller's ``gate`` authorizes it — the enforcement lives here, in the executor,
    not in some UI layer that a different caller could skip.
"""
from __future__ import annotations

import os
import re
import shlex
import subprocess
from dataclasses import dataclass, field

from . import nodes

_SLOT = re.compile(r"<([^>]*)>")
_PLACEHOLDER = re.compile(r"\{([^}]*)\}")
_WS = re.compile(r"\s+")


class CoercionError(Exception):
    """A captured value didn't satisfy its argument's type/constraint."""


class NeedsAuthorization(Exception):
    """A 'confirm'/'sudo' skill was executed without gate approval."""

    def __init__(self, skill: nodes.Skill):
        self.skill = skill
        super().__init__(f"skill {skill.name!r} requires {skill.danger!r} authorization")


# ---- matching --------------------------------------------------------------


@dataclass
class Match:
    skill: nodes.Skill
    args: dict
    pattern: str
    score: float


def _normalize(s: str) -> str:
    s = _WS.sub(" ", s.strip().lower())
    return s.strip(" .!?,;:")


def _pattern_to_regex(pattern: str) -> tuple[re.Pattern, bool, int]:
    """Compile an utter pattern to a regex. Returns (regex, anchored, literal_len)."""
    slots = _SLOT.findall(pattern)
    literal_len = len(_SLOT.sub("", pattern).replace(" ", ""))
    if not slots:
        # phrase match anywhere, on word boundaries
        rx = re.compile(rf"(?<!\w){re.escape(_normalize(pattern))}(?!\w)", re.I)
        return rx, False, literal_len
    # build an anchored full-match regex with named captures
    out = ["^"]
    last_idx = len(slots) - 1
    seen = 0
    parts = re.split(r"<[^>]*>", pattern)
    for i, lit in enumerate(parts):
        out.append(re.escape(_normalize(lit)) if lit.strip() else r"\s*")
        if i < len(slots):
            name = slots[i].strip()
            if seen == last_idx:
                out.append(rf"(?P<{name}>.+)")     # last slot: rest of the utterance
            else:
                out.append(rf"(?P<{name}>\S+)")    # middle slot: one token
            seen += 1
    out.append("$")
    return re.compile("".join(out), re.I), True, literal_len


def _coerce(arg: nodes.Arg, raw: str):
    raw = raw.strip()
    if arg.type in ("int", "number"):
        try:
            val = float(raw)
        except ValueError:
            raise CoercionError(f"{arg.name} expected a number, got {raw!r}")
        if arg.type == "int":
            if val != int(val):
                raise CoercionError(f"{arg.name} expected a whole number, got {raw!r}")
            val = int(val)
        if isinstance(arg.constraint, nodes.Range) and not (arg.constraint.lo <= val <= arg.constraint.hi):
            raise CoercionError(f"{arg.name}={val} out of range {arg.constraint.lo}..{arg.constraint.hi}")
        return val
    # word / text
    val = raw
    if arg.type == "word" and _WS.search(val):
        raise CoercionError(f"{arg.name} expected a single word, got {raw!r}")
    if isinstance(arg.constraint, nodes.MaxLen) and len(val) > arg.constraint.n:
        raise CoercionError(f"{arg.name} longer than {arg.constraint.n} chars")
    if isinstance(arg.constraint, nodes.Enum):
        lowered = {c.lower(): c for c in arg.constraint.choices}
        if val.lower() not in lowered:
            raise CoercionError(f"{arg.name}={val!r} not in {arg.constraint.choices}")
        val = lowered[val.lower()]
    return val


def match(program: nodes.Program, utterance: str) -> Match | None:
    """Best-matching skill for an utterance, with coerced args, or None."""
    norm = _normalize(utterance)
    best: Match | None = None
    for sk in program.skills:
        for pat in sk.utters:
            rx, anchored, lit_len = _pattern_to_regex(pat)
            m = rx.search(norm)
            if not m:
                continue
            try:
                args = {name: _coerce(sk.arg(name), val) for name, val in m.groupdict().items()}
            except CoercionError:
                continue          # typed mismatch → not this skill
            # an exact phrase ("open settings") is as specific as an anchored slot
            # pattern — both cover the whole utterance, so both earn the full bonus.
            full = anchored or _normalize(pat) == norm
            score = lit_len + (1000 if full else 0) - 5 * len(m.groupdict())
            if best is None or score > best.score:
                best = Match(skill=sk, args=args, pattern=pat, score=score)
    return best


# ---- execution -------------------------------------------------------------


@dataclass
class ExecResult:
    skill: str
    reply: str
    stdout: str
    command: object = None          # argv list or shell string actually run (for inspection/tests)
    dry_run: bool = False


def _render_argv(tokens: list[str], args: dict) -> list[str]:
    out = []
    for tok in tokens:
        # a token that is exactly "{name}" becomes one argv element = the raw value
        whole = _PLACEHOLDER.fullmatch(tok)
        if whole and whole.group(1).strip() in args:
            out.append(str(args[whole.group(1).strip()]))
        else:
            out.append(_PLACEHOLDER.sub(lambda m: str(args.get(m.group(1).strip(), m.group(0))), tok))
    return out


def _render_shell(template: str, args: dict) -> str:
    # every interpolation is shlex.quote'd — the value can never become syntax
    return _PLACEHOLDER.sub(
        lambda m: shlex.quote(str(args[m.group(1).strip()])) if m.group(1).strip() in args else m.group(0),
        template,
    )


def _render_reply(template: str, args: dict, stdout: str) -> str:
    def sub(m):
        key = m.group(1).strip()
        if key == "0":
            return stdout
        return str(args.get(key, m.group(0)))
    return _PLACEHOLDER.sub(sub, template or "")


def execute(skill_match: Match, gate=None, *, dry_run: bool = False, timeout: float = 15.0) -> ExecResult:
    """Run a matched skill. ``gate`` is a callable ``gate(skill) -> bool`` consulted
    for 'confirm'/'sudo' skills. ``dry_run`` renders the command but does not run it
    (used by tests to prove the rendered command is injection-safe)."""
    sk, args = skill_match.skill, skill_match.args

    if sk.danger in ("confirm", "sudo"):
        if gate is None or not gate(sk):
            raise NeedsAuthorization(sk)

    runner = sk.runner
    stdout, command = "", None

    if isinstance(runner, nodes.ArgvRunner):
        command = _render_argv(runner.tokens, args)
        if not dry_run:
            stdout = _run_capture(command, shell=False, timeout=timeout)
    elif isinstance(runner, nodes.ShellRunner):
        command = _render_shell(runner.template, args)
        if not dry_run:
            stdout = _run_capture(["bash", "-lc", command], shell=False, timeout=timeout)
    elif isinstance(runner, nodes.ReadRunner):
        path = os.path.expanduser(_render_reply(runner.path_template, args, ""))
        command = ["<read>", path]
        if not dry_run:
            try:
                with open(path) as f:
                    stdout = f.read().strip()
            except OSError as e:
                stdout = f"(could not read {path}: {e})"
    elif isinstance(runner, nodes.ReplyOnlyRunner):
        command = None

    reply = _render_reply(sk.reply, args, stdout) if sk.reply is not None else stdout
    return ExecResult(skill=sk.name, reply=reply, stdout=stdout, command=command, dry_run=dry_run)


def _run_capture(argv: list[str], *, shell: bool, timeout: float) -> str:
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return f"(command failed: {e})"
    return (p.stdout or p.stderr or "").strip()
