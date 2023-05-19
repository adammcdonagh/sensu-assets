#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Helper class to define the exit hook."""
import sys


class ExitHook:
    """Class to define the exit hook."""

    def __init__(self):
        """Create the exit hook."""
        self._orig_exit = None
        self.exit_code = None
        self.exception = None

    def hook(self):
        """Hook into the exit handler."""  # noqa: D401
        self._orig_exit = sys.exit
        sys.exit = self.exit
        sys.excepthook = self.exc_handler

    def exit(self, code=0):
        """Exit the program with the required exit code."""
        self.exit_code = code
        self._orig_exit(code)

    def exc_handler(self, _exc_type, exc, *_args):
        """Set any exceptions."""
        self.exception = exc
