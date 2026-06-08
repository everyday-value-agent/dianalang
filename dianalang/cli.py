"""`dianac` — the DianaLang command-line compiler.

    dianac check  <file.dl>                 parse + validate, list diagnostics
    dianac match  <file.dl> "<utterance>"   show the matched skill, args, command
    dianac run    <file.dl> "<utterance>"   match + execute (--yes authorizes gated skills)
    dianac build  <file.dl> [-o out.py]     compile to standalone Python
    dianac test   <file.dl>                 prove no skill can be shell-injected
"""
from __future__ import annotations

import argparse
import sys

from . import codegen, prove
from .errors import DianaLangError
from .parser import parse
from .runtime import NeedsAuthorization, execute, match
from .validate import validate


def _load(path: str):
    with open(path) as f:
        return f.read()


def _print_diags(diags) -> int:
    errs = [d for d in diags if d.kind == "error"]
    for d in diags:
        print(("  ✗ " if d.kind == "error" else "  ! ") + str(d))
    return 1 if errs else 0


def cmd_check(args) -> int:
    try:
        program = parse(_load(args.file))
    except DianaLangError as e:
        print(f"{args.file}: parse failed")
        return _print_diags(e.diagnostics) or 1
    diags = validate(program)
    if not diags:
        print(f"{args.file}: ok — {len(program.skills)} skills, no issues ✓")
        return 0
    rc = _print_diags(diags)
    n_err = sum(1 for d in diags if d.kind == "error")
    print(f"{args.file}: {n_err} error(s), {len(diags) - n_err} warning(s)")
    return rc


def cmd_match(args) -> int:
    program = _compiled_or_exit(args.file)
    m = match(program, args.utterance)
    if m is None:
        print(f"no skill matched {args.utterance!r}")
        return 1
    print(f"skill:   {m.skill.name}  (danger={m.skill.danger})")
    print(f"pattern: {m.pattern!r}")
    print(f"args:    {m.args}")
    try:
        res = execute(m, gate=lambda sk: True, dry_run=True)
        print(f"command: {res.command!r}")
        print(f"reply:   {res.reply!r}")
    except Exception as e:                      # noqa: BLE001 - report, don't crash the CLI
        print(f"(dry-run render failed: {e})")
    return 0


def cmd_run(args) -> int:
    program = _compiled_or_exit(args.file)
    m = match(program, args.utterance)
    if m is None:
        print(f"no skill matched {args.utterance!r}")
        return 1
    gate = (lambda sk: True) if args.yes else (lambda sk: False)
    try:
        res = execute(m, gate=gate)
    except NeedsAuthorization as e:
        print(f"refused: {e}. Re-run with --yes to authorize.")
        return 2
    print(res.reply)
    return 0


def cmd_build(args) -> int:
    program = _compiled_or_exit(args.file)
    out = args.out or (args.file.rsplit(".", 1)[0] + "_compiled.py")
    code = codegen.generate(program, source=args.file, out=out)
    with open(out, "w") as f:
        f.write(code)
    print(f"wrote {out} ({len(program.skills)} skills)")
    return 0


def cmd_test(args) -> int:
    program = _compiled_or_exit(args.file)
    probes = prove.probe_program(program)
    passed, total = prove.summary(probes)
    failures = [p for p in probes if not p.safe]
    if not total:
        print("no shell/argv skills to prove (nothing injectable) ✓")
        return 0
    for p in failures:
        print(f"  ✗ {p.skill}.{p.arg} payload={p.payload!r} → {p.reason}\n      rendered: {p.rendered}")
    status = "✓ INJECTION-PROOF" if not failures else "✗ INJECTABLE"
    print(f"{args.file}: {passed}/{total} injection probes safe — {status}")
    return 0 if not failures else 1


def _compiled_or_exit(path: str):
    try:
        program = parse(_load(path))
    except DianaLangError as e:
        print(f"{path}: parse failed", file=sys.stderr)
        _print_diags(e.diagnostics)
        sys.exit(1)
    errs = [d for d in validate(program) if d.kind == "error"]
    if errs:
        print(f"{path}: validation failed", file=sys.stderr)
        _print_diags(errs)
        sys.exit(1)
    return program


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="dianac", description="The DianaLang compiler.")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check", help="parse + validate")
    c.add_argument("file")
    c.set_defaults(func=cmd_check)

    m = sub.add_parser("match", help="show the matched skill for an utterance")
    m.add_argument("file")
    m.add_argument("utterance")
    m.set_defaults(func=cmd_match)

    r = sub.add_parser("run", help="match + execute an utterance")
    r.add_argument("file")
    r.add_argument("utterance")
    r.add_argument("--yes", action="store_true", help="authorize confirm/sudo skills")
    r.set_defaults(func=cmd_run)

    b = sub.add_parser("build", help="compile to standalone Python")
    b.add_argument("file")
    b.add_argument("-o", "--out", default=None)
    b.set_defaults(func=cmd_build)

    t = sub.add_parser("test", help="prove no skill can be shell-injected")
    t.add_argument("file")
    t.set_defaults(func=cmd_test)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
