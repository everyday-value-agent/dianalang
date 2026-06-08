"""Diagnostics for DianaLang — every error carries a line so the message is
actionable (the project's no-silent-failures rule, applied to a compiler)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Diagnostic:
    line: int
    message: str
    kind: str = "error"          # "error" | "warning"

    def __str__(self) -> str:
        return f"line {self.line}: {self.kind}: {self.message}"


class DianaLangError(Exception):
    """Raised when compilation cannot proceed. Holds one or more diagnostics."""

    def __init__(self, diagnostics: list[Diagnostic]):
        self.diagnostics = diagnostics
        super().__init__("\n".join(str(d) for d in diagnostics))
