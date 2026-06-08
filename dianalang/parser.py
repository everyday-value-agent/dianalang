"""Recursive-descent parser: tokens -> Program AST.

Grammar (v0.1):

    program   := skill*
    skill     := 'skill' IDENT '{' stmt* '}'
    stmt      := utter | argdef | danger | run | reply
    utter     := 'utter' STRING (',' STRING)*
    argdef    := 'arg' IDENT ':' type constraint?
    type      := 'int' | 'number' | 'word' | 'text'
    constraint:= 'range' NUMBER '..' NUMBER
               | 'in' '(' atom (',' atom)* ')'
               | 'max' NUMBER
    danger    := 'safe' | 'confirm' | 'sudo'
    run       := 'run' ( 'shell' STRING
                       | 'argv' '[' STRING (',' STRING)* ']'
                       | 'read' STRING
                       | 'reply_only' )
    reply     := 'reply' STRING
    atom      := STRING | IDENT | NUMBER

Errors accumulate (with line numbers) and are raised together so one bad file
reports every problem, not just the first.
"""
from __future__ import annotations

from . import nodes
from .errors import Diagnostic, DianaLangError
from .lexer import Token, tokenize

_TYPES = {"int", "number", "word", "text"}
_DANGERS = {"safe", "confirm", "sudo"}
_STMT_KEYWORDS = {"utter", "arg", "run", "reply"} | _DANGERS


class Parser:
    def __init__(self, tokens: list[Token]):
        self.toks = tokens
        self.pos = 0
        self.diags: list[Diagnostic] = []

    # -- token helpers --
    def peek(self) -> Token:
        return self.toks[self.pos]

    def at(self, kind: str) -> bool:
        return self.peek().kind == kind

    def advance(self) -> Token:
        t = self.toks[self.pos]
        if t.kind != "EOF":
            self.pos += 1
        return t

    def expect(self, kind: str) -> Token:
        t = self.peek()
        if t.kind != kind:
            raise self._err(t, f"expected {kind!r}, got {t.kind!r} ({t.value!r})")
        return self.advance()

    def _err(self, tok: Token, msg: str) -> DianaLangError:
        return DianaLangError([Diagnostic(tok.line, msg)])

    # -- entry --
    def parse(self) -> nodes.Program:
        prog = nodes.Program()
        while not self.at("EOF"):
            if self.at("skill"):
                prog.skills.append(self._skill())
            else:
                t = self.peek()
                self.diags.append(Diagnostic(t.line, f"expected 'skill', got {t.value!r}"))
                self._recover_to_skill()
        if self.diags:
            raise DianaLangError(self.diags)
        return prog

    def _recover_to_skill(self) -> None:
        while not self.at("EOF") and not self.at("skill"):
            self.advance()

    # -- skill block --
    def _skill(self) -> nodes.Skill:
        kw = self.expect("skill")
        name = self.expect("IDENT").value
        skill = nodes.Skill(name=name, line=kw.line)
        self.expect("LBRACE")
        seen_danger = False
        while not self.at("RBRACE") and not self.at("EOF"):
            t = self.peek()
            if t.kind == "utter":
                self.advance()
                skill.utters.extend(self._string_list())
            elif t.kind == "arg":
                skill.args.append(self._argdef())
            elif t.kind in _DANGERS:
                self.advance()
                if seen_danger:
                    self.diags.append(Diagnostic(t.line, f"duplicate danger level {t.value!r}"))
                skill.danger = t.value
                seen_danger = True
            elif t.kind == "run":
                skill.runner = self._run()
            elif t.kind == "reply":
                self.advance()
                skill.reply = self.expect("STRING").value
            else:
                self.diags.append(Diagnostic(t.line, f"unexpected {t.value!r} inside skill {name!r}"))
                self.advance()
        self.expect("RBRACE")
        return skill

    def _string_list(self) -> list[str]:
        out = [self.expect("STRING").value]
        while self.at("COMMA"):
            self.advance()
            out.append(self.expect("STRING").value)
        return out

    def _argdef(self) -> nodes.Arg:
        kw = self.expect("arg")
        name = self.expect("IDENT").value
        self.expect("COLON")
        ttok = self.peek()
        if ttok.kind not in _TYPES:
            raise self._err(ttok, f"expected a type (int/number/word/text), got {ttok.value!r}")
        self.advance()
        constraint = self._constraint(ttok.kind)
        return nodes.Arg(name=name, type=ttok.kind, constraint=constraint, line=kw.line)

    def _constraint(self, arg_type: str):
        t = self.peek()
        if t.kind == "range":
            self.advance()
            lo = float(self.expect("NUMBER").value)
            self.expect("RANGE")
            hi = float(self.expect("NUMBER").value)
            return nodes.Range(lo, hi)
        if t.kind == "in":
            self.advance()
            self.expect("LPAREN")
            choices = [self._atom()]
            while self.at("COMMA"):
                self.advance()
                choices.append(self._atom())
            self.expect("RPAREN")
            return nodes.Enum(choices)
        if t.kind == "max":
            self.advance()
            return nodes.MaxLen(int(float(self.expect("NUMBER").value)))
        return None

    def _atom(self) -> str:
        t = self.peek()
        if t.kind in ("STRING", "IDENT", "NUMBER"):
            return self.advance().value
        raise self._err(t, f"expected a value, got {t.kind!r}")

    def _run(self):
        self.expect("run")
        t = self.peek()
        if t.kind == "shell":
            self.advance()
            return nodes.ShellRunner(self.expect("STRING").value, line=t.line)
        if t.kind == "argv":
            self.advance()
            self.expect("LBRACK")
            toks = [self.expect("STRING").value]
            while self.at("COMMA"):
                self.advance()
                toks.append(self.expect("STRING").value)
            self.expect("RBRACK")
            return nodes.ArgvRunner(toks, line=t.line)
        if t.kind == "read":
            self.advance()
            return nodes.ReadRunner(self.expect("STRING").value, line=t.line)
        if t.kind == "reply_only":
            self.advance()
            return nodes.ReplyOnlyRunner(line=t.line)
        raise self._err(t, f"expected shell/argv/read/reply_only after 'run', got {t.value!r}")


def parse(src: str) -> nodes.Program:
    return Parser(tokenize(src)).parse()
