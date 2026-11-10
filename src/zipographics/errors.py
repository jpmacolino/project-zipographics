"""Exceptions shared by the build modules (kept separate to avoid import cycles)."""

from __future__ import annotations


class BuildError(Exception):
    """A failed build step. ``exit_code`` is the CLI exit code (5 = validation failure)."""

    def __init__(self, message: str, exit_code: int = 5) -> None:
        super().__init__(message)
        self.exit_code = exit_code
