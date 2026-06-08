"""Hand-written lexer for DianaLang. Stdlib-only, no regex engine for the core
scan loop so token positions (and thus error lines) are exact.

Whitespace and `# comments` are skipped. The language is newline-insensitive:
statements are keyword-led, so the parser never needs newline tokens.
"""
from __future__ import annotations

from dataclasses import dataclass

from .errors import Diagnostic, DianaLangError

KEYWORDS = {
    "skill", "utter", "arg", "run", "reply",
    "safe", "confirm", "sudo",
    "shell", "argv", "read", "reply_only",
    "int", "number", "word", "text",
    "range", "in", "max",
}

# Single/double-char punctuation → token kind.
PUNCT = {
    "{": "LBRACE", "}": "RBRACE",
    "[": "LBRACK", "]": "RBRACK",
    "(": "LPAREN", ")": "RPAREN",
    ":": "COLON", ",": "COMMA",
    "..": "RANGE",
}


@dataclass
class Token:
    kind: str        # keyword text (e.g. "skill"), or "STRING"/"NUMBER"/"IDENT", or a PUNCT kind
    value: str
    line: int

    def __repr__(self) -> str:
        return f"Token({self.kind!r}, {self.value!r}, L{self.line})"


def _is_ident_start(c: str) -> bool:
    return c.isalpha() or c == "_"


def _is_ident_part(c: str) -> bool:
    return c.isalnum() or c == "_"


def tokenize(src: str) -> list[Token]:
    tokens: list[Token] = []
    i, line, n = 0, 1, len(src)
    diags: list[Diagnostic] = []

    while i < n:
        c = src[i]

        # whitespace
        if c == "\n":
            line += 1
            i += 1
            continue
        if c.isspace():
            i += 1
            continue

        # comments: `# ...` to end of line
        if c == "#":
            while i < n and src[i] != "\n":
                i += 1
            continue

        # strings: "..." with \" and \\ escapes
        if c == '"':
            j = i + 1
            buf = []
            closed = False
            while j < n:
                cj = src[j]
                if cj == "\\" and j + 1 < n:
                    nxt = src[j + 1]
                    buf.append({"n": "\n", "t": "\t", '"': '"', "\\": "\\"}.get(nxt, nxt))
                    j += 2
                    continue
                if cj == '"':
                    closed = True
                    j += 1
                    break
                if cj == "\n":
                    break          # unterminated on this line
                buf.append(cj)
                j += 1
            if not closed:
                diags.append(Diagnostic(line, "unterminated string literal"))
                i = j
                continue
            tokens.append(Token("STRING", "".join(buf), line))
            i = j
            continue

        # two-char punctuation first (`..`)
        if src[i:i + 2] == "..":
            tokens.append(Token("RANGE", "..", line))
            i += 2
            continue

        # single-char punctuation
        if c in PUNCT:
            tokens.append(Token(PUNCT[c], c, line))
            i += 1
            continue

        # numbers (int or float; no leading sign — ranges use `lo..hi`)
        if c.isdigit():
            j = i
            while j < n and (src[j].isdigit() or src[j] == "."):
                # stop before a `..` range operator
                if src[j] == "." and src[j:j + 2] == "..":
                    break
                j += 1
            tokens.append(Token("NUMBER", src[i:j], line))
            i = j
            continue

        # identifiers / keywords
        if _is_ident_start(c):
            j = i
            while j < n and _is_ident_part(src[j]):
                j += 1
            word = src[i:j]
            kind = word if word in KEYWORDS else "IDENT"
            tokens.append(Token(kind, word, line))
            i = j
            continue

        diags.append(Diagnostic(line, f"unexpected character {c!r}"))
        i += 1

    if diags:
        raise DianaLangError(diags)

    tokens.append(Token("EOF", "", line))
    return tokens
