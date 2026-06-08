"""The headline guarantee: no DianaLang skill can be shell-injected. We render
real injection payloads through the executor (dry-run) and prove they stay inert.
"""
import pathlib
import shlex

from dianalang import compile_source
from dianalang.runtime import Match, execute
from dianalang.prove import probe_program, summary

EXAMPLE = (pathlib.Path(__file__).parent.parent / "examples" / "diana.dl").read_text()


def test_example_program_is_injection_proof():
    probes = probe_program(compile_source(EXAMPLE))
    passed, total = summary(probes)
    assert total > 0
    failures = [p for p in probes if not p.safe]
    assert not failures, "\n".join(f"{p.skill}.{p.arg} {p.payload!r}: {p.rendered}" for p in failures)
    assert passed == total


def test_largest_files_quotes_the_path():
    # the exact skill that was a real voice->RCE hole in Diana's Python
    prog = compile_source(EXAMPLE)
    sk = prog.skill("largest_files")
    payload = "'$(reboot)"
    res = execute(Match(sk, {"path": payload}, sk.utters[0], 0), dry_run=True)
    # the payload must survive shell parsing as ONE inert token
    assert payload in shlex.split(res.command)
    # and the dangerous substitution must NOT be a bare token
    assert "$(reboot)" not in shlex.split(res.command) or payload in shlex.split(res.command)


def test_shell_reminder_quotes_free_text():
    prog = compile_source(EXAMPLE)
    sk = prog.skill("reminder")
    payload = "x'; rm -rf ~; echo '"
    res = execute(Match(sk, {"note": payload}, sk.utters[0], 0), gate=lambda s: True, dry_run=True)
    assert payload in shlex.split(res.command)
    assert "rm" not in [t for t in shlex.split(res.command) if t == "rm"]


def test_argv_values_never_split():
    prog = compile_source(EXAMPLE)
    sk = prog.skill("web_search")
    payload = "hello; rm -rf ~"
    res = execute(Match(sk, {"query": payload}, sk.utters[0], 0), dry_run=True)
    # the whole payload lives inside a single argv element (the URL), never its own arg
    assert any(payload in tok for tok in res.command)
    assert "rm" not in res.command
