#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Helper class to define the exit hook."""
import sys


class ExitHook:
    """Class to define the exit hook."""

    def __init__(self) -> None:
        """Create the exit hook."""
        self._orig_exit = None
        self.exit_code = None
        self.exception = None

    def hook(self) -> None:
        """Hook into the exit handler."""  # noqa: D401
        self._orig_exit = sys.exit  # type: ignore[assignment]
        sys.exit = self.exit  # type: ignore[assignment]
        sys.excepthook = self.exc_handler

    def exit(self, code: int | None = 0) -> None:
        """Exit the program with the required exit code."""
        self.exit_code = code  # type: ignore[assignment]
        if self._orig_exit:
            self._orig_exit(code)  # type: ignore[unreachable]

    def exc_handler(self, _exc_type, exc, *_args) -> None:  # type: ignore[no-untyped-def]
        """Set any exceptions."""
        self.exception = exc
