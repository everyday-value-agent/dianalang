"""AST node types for DianaLang. Plain dataclasses — the parser produces them,
the validator checks them, the runtime and codegen consume them."""
from __future__ import annotations

from dataclasses import dataclass, field

# ---- argument constraints --------------------------------------------------


@dataclass
class Range:
    lo: float
    hi: float


@dataclass
class Enum:
    choices: list[str]


@dataclass
class MaxLen:
    n: int


Constraint = "Range | Enum | MaxLen | None"


@dataclass
class Arg:
    name: str
    type: str                       # "int" | "number" | "word" | "text"
    constraint: object = None       # Range | Enum | MaxLen | None
    line: int = 0


# ---- runners ---------------------------------------------------------------


@dataclass
class ShellRunner:
    template: str                   # bash -lc; {arg} interpolations are auto-shlex.quoted
    line: int = 0


@dataclass
class ArgvRunner:
    tokens: list[str]               # exec'd directly, no shell; {arg} fills one argv element
    line: int = 0


@dataclass
class ReadRunner:
    path_template: str              # read a file's text; path built argv-safe, no shell
    line: int = 0


@dataclass
class ReplyOnlyRunner:
    line: int = 0


Runner = "ShellRunner | ArgvRunner | ReadRunner | ReplyOnlyRunner"


# ---- skills + program ------------------------------------------------------


@dataclass
class Skill:
    name: str
    utters: list[str] = field(default_factory=list)
    args: list[Arg] = field(default_factory=list)
    danger: str = ""                # "safe" | "confirm" | "sudo"; "" = unset (a validation error)
    runner: object = None           # one of the Runner types
    reply: str | None = None
    line: int = 0

    def arg(self, name: str) -> Arg | None:
        for a in self.args:
            if a.name == name:
                return a
        return None


@dataclass
class Program:
    skills: list[Skill] = field(default_factory=list)

    def skill(self, name: str) -> Skill | None:
        for s in self.skills:
            if s.name == name:
                return s
        return None
