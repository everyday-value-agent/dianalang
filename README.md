# DianaLang

**A tiny declarative language for voice-assistant skills, where safety is a language feature.**

In a normal assistant, "don't let a misheard command run `rm -rf`" and "don't let
an app name shell-inject" are conventions you hope every contributor remembers.
DianaLang makes them **grammar**. A program that compiles is a program that:

- declares an explicit **danger level** on every skill (no accidental `safe` default);
- never hides a destructive command inside a `safe` skill;
- **cannot be shell-injected** — every interpolation is bound to a typed argument and auto-sanitized;
- enforces its gate at the **executor** (the choke point), not in some UI layer a different caller can skip.

> It was built to fix a real bug. A voice assistant (“Diana”) had a hand-written Python skill:
> ```python
> _run(["bash", "-lc", f"du -ah {path!r} ... | sort -rh | head -6"])   # {path} from speech
> ```
> `{path!r}` *looks* quoted, but Python's `repr()` isn't shell-safe — a spoken path like
> `'$(reboot)` executes. In DianaLang that same skill is injection-proof by construction:

```dl
skill largest_files {
    utter "what are the biggest files in <path>", "largest files in <path>"
    arg path : text max 300
    safe
    run shell "du -ah {path} 2>/dev/null | sort -rh | head -6"   # {path} auto-quoted
    reply "Largest items under {path}:\n{0}"
}
```

```console
$ dianac test examples/diana.dl
examples/diana.dl: 44/44 injection probes safe — ✓ INJECTION-PROOF
```

---

## Install

```bash
git clone https://github.com/Thanukamax/dianalang
cd dianalang
pip install -e .       # stdlib-only — no dependencies
```

## The compiler — `dianac`

```bash
dianac check  examples/diana.dl                       # parse + validate
dianac match  examples/diana.dl "set volume to 40"    # show matched skill, args, command
dianac run    examples/diana.dl "reboot" --yes        # match + execute (gated skills need --yes)
dianac build  examples/diana.dl -o diana_compiled.py  # compile to standalone Python
dianac test   examples/diana.dl                       # prove no skill can be shell-injected
```

```console
$ dianac match examples/diana.dl "set volume to 40"
skill:   set_volume  (danger=safe)
pattern: 'set volume to <level>'
args:    {'level': 40}
command: ['wpctl', 'set-volume', '@DEFAULT_AUDIO_SINK@', '40%']
reply:   'Volume set to 40 percent.'
```

## The language

```
skill <name> {
    utter "<pattern>" [, "<pattern>" ...]   # trigger phrases; <slot> captures an arg
    arg <name> : <type> [<constraint>]      # int | number | word | text
    <danger>                                # safe | confirm | sudo   (required)
    run <runner>                            # how it executes (below)
    reply "<template>"                      # {arg} and {0}=command output
}
```

**Types & constraints**

| type | example | constraint |
|---|---|---|
| `int` | `arg level : int range 0..150` | `range lo..hi` |
| `number` | `arg ratio : number range 0..1` | `range lo..hi` |
| `word` | `arg color : word in (red, green, blue)` | `in (...)` |
| `text` | `arg note : text max 200` | `max N` |

**Runners**

| runner | executes | injection model |
|---|---|---|
| `run argv ["wpctl", "set-volume", "{level}%"]` | argv, no shell | inherently safe — a value is one literal argument |
| `run shell "du -ah {path} \| sort"` | `bash -lc` | every `{arg}` is `shlex.quote`d |
| `run read "/sys/class/power_supply/BAT0/capacity"` | reads a file | path built without a shell |
| `run reply_only` | nothing | static reply |

**Danger levels** are enforced in the executor: a `confirm`/`sudo` skill raises
`NeedsAuthorization` unless the caller's `gate(skill) -> bool` approves it.

## What the compiler rejects

These programs **do not compile** — each is a class of bug turned into a compile error:

```dl
skill x { utter "x" run reply_only }                       # ✗ no danger level declared
skill x { utter "wipe <p>" arg p:text safe                 # ✗ destructive command in a 'safe' skill
          run shell "rm -rf {p}" }
skill x { utter "x" safe run argv ["echo","{ghost}"] }     # ✗ {ghost} has no matching arg
skill x { utter "say <word>" safe run reply_only }         # ✗ slot <word> has no matching arg
skill x { utter "x <n>" arg n:int in (1,2) safe ... }      # ✗ enum constraint on a numeric arg
```

## Embedding in Python

```python
from dianalang import compile_source, match, execute

program = compile_source(open("diana.dl").read())     # raises on any error diagnostic
m = match(program, "set volume to 40")                # -> Match(skill, args, ...) or None
result = execute(m, gate=lambda sk: confirm_with_user(sk))
print(result.reply)                                   # "Volume set to 40 percent."
```

Or compile to a standalone module and ship that:

```python
import diana_compiled
res = diana_compiled.dispatch("reboot", gate=ask_passphrase)
```

## How it works

```
.dl source ─▶ lexer ─▶ parser ─▶ AST ─▶ validator ─▶ ┬─▶ runtime  (match + safe execute)
              (tokens) (recursive  (nodes) (safety        └─▶ codegen  (standalone .py)
                        descent)            rules)
```

- **`lexer.py`** — hand-written tokenizer, exact line tracking for actionable errors.
- **`parser.py`** — recursive descent; accumulates every error, not just the first.
- **`validate.py`** — the safety rules (this is the heart of the language).
- **`runtime.py`** — utterance→skill matcher with typed-arg coercion + the injection-proof executor.
- **`prove.py`** — the exhaustive injection prover behind `dianac test`.
- **`codegen.py`** — emits a standalone, auditable Python module.

## Tests

```bash
python -m pytest -q      # 50 tests: lexer, parser, validation, runtime, codegen, injection
```

The injection suite renders real payloads (`'$(reboot)`, `"; rm -rf ~`, backticks, pipes)
through every shell/argv skill and proves each one survives as a single inert token.

## License

MIT — see [LICENSE](LICENSE).
