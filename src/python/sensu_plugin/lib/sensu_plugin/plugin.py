#!/usr/bin/env python
# -*- coding: utf-8 -*-
# pylint: disable=no-member
"""Class that defined a generic Sensu plugin.

This might be a class that runs checks, or collects metrics.
"""
import argparse
import atexit
import os
import platform
import sys
import time
import traceback
from collections import namedtuple
from dataclasses import dataclass

from sensu_plugin.asset import SensuAsset
from sensu_plugin.exithook import ExitHook

# create a namedtuple of all valid exit codes
ExitCode = namedtuple("ExitCode", ["OK", "WARNING", "CRITICAL", "UNKNOWN"])


@dataclass
class SensuPlugin(SensuAsset):  # pylint: disable=too-many-instance-attributes
    """Base class used by both checks and metrics plugins."""

    SENSU_CACHE_DIR: str  # pylint: disable=invalid-name
    plugin_info: dict
    parser: argparse.ArgumentParser
    options: argparse.Namespace
    exit_code: ExitCode
    test_mode: bool
    _hook: ExitHook

    def __init__(self, autorun: bool = True):
        """Create base class and initialise logging."""
        # Call super class which will sort out the logging
        super().__init__()

        self.exit_code = ExitCode(0, 1, 2, 3)
        self.test_mode = False
        self._hook = ExitHook()

        # Determine the CACHE_DIR based on the platform, unless its overridden in the environment
        if os.environ.get("SENSU_CACHE_DIR"):
            self.SENSU_CACHE_DIR = os.environ.get("SENSU_CACHE_DIR", "")
        else:
            # If windows then use the default windows cache dir
            # if macos then use /tmp/sensu-agent
            # oterhwise use /var/cache/sensu/sensu-agent
            if platform.system() == "Windows":
                self.SENSU_CACHE_DIR = "C:\\ProgramData\\sensu\\cache\\sensu-agent"
            elif platform.system() == "Darwin":
                self.SENSU_CACHE_DIR = "/tmp/sensu-agent"
            else:
                self.SENSU_CACHE_DIR = "/var/cache/sensu/sensu-agent"

        self.plugin_info = {"check_name": None, "message": None, "status": None}

        # create a method for each of the exit codes
        # and register as exit functions
        self._hook.hook()

        for field in self.exit_code._fields:
            self.__make_dynamic(field)

        atexit.register(self.__exitfunction)

        # Prepare command line arguments
        self.parser = argparse.ArgumentParser(
            formatter_class=argparse.ArgumentDefaultsHelpFormatter
        )
        if hasattr(self, "setup"):
            self.setup()  # mypy: ignore-errors # type: ignore
        (self.options, self.remain) = self.parser.parse_known_args()

        if autorun:
            self.run()

    def sanitise_arguments(self, args: tuple) -> tuple:
        """Validate arguments.

        Checks whether the arguments have been passed by a dynamic status code
        or if the output method is being called directly
        extract the required tuple if called using dynamic function

        Args:
            args: tuple of arguments

        Returns:
            tuple of arguments
        """
        if len(args) == 1 and isinstance(args[0], tuple):
            args = args[0]
        # check to see whether output is running after being called by an empty
        # dynamic function.
        if args[0] is None:
            pass
        # check to see whether output is running after being called by a
        # dynamic whilst containing a message.
        elif isinstance(args[0], Exception) or len(args) == 1:
            print(args[0])

        return args

    def output(self, args: tuple) -> None:
        """Print the output message."""
        print(f"SensuPlugin: {' '.join(str(a) for a in args)}")

    def output_metrics(self, args: list) -> None:
        """Print the output message."""
        # sanitise the arguments
        if args := self.sanitise_arguments(args):  # type: ignore[arg-type, assignment]
            # convert the arguments to a list
            args = list(args)
            # add the timestamp if required
            if len(args) < 3:
                args.append(None)
            if args[2] is None:
                args[2] = int(time.time())
            # produce the output
            print(" ".join(str(s) for s in args[0:3]))

    def __make_dynamic(self, method: str) -> None:
        """Create a method for each of the exit codes."""

        def dynamic(*args: None | tuple, **kwargs: None | tuple) -> None:
            self.plugin_info["status"] = method

            if (
                "metrics_only" in self.options and not self.options.metrics_only
            ) or "metrics_only" not in self.options:
                severity_msg = (
                    f"SEV:{kwargs['severity']} " if "severity" in kwargs else ""
                )
                team_msg = f"TEAM:{kwargs['team']} " if "team" in kwargs else ""
                source_msg = f"SOURCE:{kwargs['source']} " if "source" in kwargs else ""

                self.output(  # pylint: disable=unexpected-keyword-arg
                    args, severity=severity_msg, team=team_msg, source=source_msg  # type: ignore[call-arg]
                )
            if "exit" in kwargs and kwargs["exit"]:
                sys.exit(getattr(self.exit_code, method))

        method_lc = method.lower()
        dynamic.__doc__ = f"{method_lc} method"
        dynamic.__name__ = method_lc
        setattr(self, dynamic.__name__, dynamic)

    def run(self) -> None:
        """Method should be overwritten by inherited classes."""  # noqa: D401
        self.warning("Not implemented! You should override SensuPlugin.run()")  # type: ignore[attr-defined]

    def __exitfunction(self) -> None:
        """Ensure that the plugin exits correctly.

        Method called by exit hook, ensures that both an exit code and
        output is supplied, also catches errors.
        """
        if (
            self._hook.exit_code is None
            and self._hook.exception is None
            and not self.test_mode
        ):
            print("Check did not exit! You should call an exit code method.")
            sys.stdout.flush()
            sys.exit(1)
        elif self._hook.exception:
            print(  # type: ignore[unreachable] # This is a false positive
                f"Check failed to run: {sys.last_type}, {traceback.format_tb(sys.last_traceback)} - {self._hook.exception}"
            )
            sys.stdout.flush()
            sys.exit(2)
