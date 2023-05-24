#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Basic script to collect filesystem metrics on Unix systems and generate alerts or metric output for Sensu.

This is compatible with *nix systems only (not Windows).
"""
import argparse
import json
import logging
import os
import platform
import re
import shutil
import subprocess
import textwrap

from sensu_plugin import SensuPluginCheck, Threshold

FILESYSTEM_OVERRIDE_REGEX = (
    r"^([^,]+?),([YN])(?:,(\d+)(?:,(\d+)(?:,([^,]+?)(?:,(Minor|Major|Crit))*)*)*)*$"
)


class LinuxFilesystemMetrics(SensuPluginCheck):
    """Class that collects filesystem metrics on Linux."""

    def setup(self) -> None:
        """Set up arguments.

        Setup is called with self.parser set and is responsible for setting up
        self.options before the run method is called
        """
        self.parser.add_argument(
            "-v",
            "--verbose",
            required=False,
            help="turn on verbose output",
            action="store_true",
        )

        self.parser.add_argument(
            "-m",
            "--metrics_only",
            required=False,
            help="output metrics only",
            action="store_true",
        )

        self.parser.add_argument(
            "-c",
            "--check_only",
            required=False,
            help="output check result only",
            action="store_true",
        )

        self.parser.add_argument(
            "--default_warn",
            required=False,
            help="default warn percent used threshold",
            type=int,
            default=95,
        )
        self.parser.add_argument(
            "--default_crit",
            required=False,
            help="default critical percent used threshold",
            type=int,
            default=85,
        )
        self.parser.add_argument(
            "--min_severity",
            required=False,
            help="the lowest severity to alert at for the warn threshold",
            type=str,
            default="Major",
        )

        self.parser.add_argument(
            "--default_team",
            required=False,
            help="the default team that alert should go to",
            type=str,
            default=None,
        )

        self.parser.add_argument(
            "--filesystem_override",
            required=False,
            help="override default thresholds for a filesystem. Can be specified multiple files for several filesystems",
            type=filesystem_override_type,
            action="append",
        )

        self.parser.add_argument(
            "--thresholds_file",
            required=False,
            help="JSON file containing threshold overrides to use instead of command line arguments",
            type=str,
            default="/var/cache/sensu/sensu-agent/filesystems.json",
        )

        self.parser.description = textwrap.dedent(
            """
                IMPORTANT:
                The thresholds_file should be a JSON file containing a list of threshold overrides.

                If no thresholds_file is defined, and no default_warn or default_crit is defined, then no thresholds will be checked, and the check will always return OK
            """
        )

    def run(self) -> None:
        """Run the actual check."""
        if self.options.verbose:
            self.logger.setLevel(logging.DEBUG)

        self.logger.debug("Running LinuxFilesystemMetrics")

        # Load default thresholds
        # This script just has 1 set of thresholds by default - The warn percent and crit percent
        threshold = Threshold(
            warn_threshold=self.options.default_warn,
            crit_threshold=self.options.default_crit,
            min_severity=self.options.min_severity,
            team=self.options.default_team,
        )
        self.thresholds.append(threshold)

        self._process_thresholds_file()

        rc = 0
        result_message = "Check ran OK"

        # Determine the OS
        mounts = []
        filesystem_column_index = 0
        mount_column_index = 0
        if platform.system() == "Linux":
            filesystem_column_index = 2
            mount_column_index = 1
            with open("/proc/mounts", "r", encoding="utf-8") as file_:
                mounts = file_.readlines()
        elif platform.system() == "Darwin":
            filesystem_column_index = 3
            mount_column_index = 2
            mounts = (
                subprocess.run(["mount"], stdout=subprocess.PIPE, check=True)
                .stdout.decode("utf-8")
                .splitlines()
            )

        for line in mounts:
            line_split = line.split(" ", maxsplit=3)
            mount_point = line_split[mount_column_index]
            filesystem_type = line_split[filesystem_column_index]
            if re.search(r"(ext[0-9]|zfs|apfs)", filesystem_type):
                _, used, free = shutil.disk_usage(mount_point)
                used_percent = used / (free + used) * 100

                if not self.options.check_only or self.options.metrics_only:
                    self.output_metrics(
                        [f"os.filesystem.used_bytes;filesystem={mount_point}", used]
                    )
                    self.output_metrics(
                        [f"os.filesystem.free_bytes;filesystem={mount_point}", free]
                    )
                    self.output_metrics(
                        [
                            f"os.filesystem.used_percent;filesystem={mount_point}",
                            used_percent,
                        ]
                    )

                if not self.options.metrics_only or self.options.check_only:
                    # Determine thresholds
                    # Pass to threshold handler
                    threshold_result = self.process_value(
                        mount_point,
                        used_percent,
                        ok_message=f"Filesystem usage for {mount_point} is OK ({used_percent:.3g}::ALERT_TYPE:: used)",
                        alert_message=f"Filesystem usage for {mount_point} > ::THRESHOLD::::ALERT_TYPE:: ({used_percent:.3g}::ALERT_TYPE:: used)",
                        alert_type="%",
                    )
                    result_message, rc = self.process_output_and_rc(
                        threshold_result,
                        result_message,
                        "Some filesystems exceed the threshold",
                    )
        self.return_final_output(rc, result_message)

    def _process_thresholds_file(self) -> None:  # pylint: disable=too-many-branches
        # Handle any threshold overrides
        if os.path.exists(self.options.thresholds_file):
            with open(self.options.thresholds_file, mode="r", encoding="utf-8") as file:
                json_file = json.load(file)
                for threshold in json_file:
                    logging.debug(threshold)
                    # Create threshold object
                    kwargs = {
                        "id": threshold["id"],
                        "ignore": threshold["ignore"]
                        if "ignore" in threshold
                        else False,
                    }
                    args = ("warn_threshold", "crit_threshold", "team", "min_severity")
                    for arg in args:
                        if arg in threshold:
                            kwargs[arg] = threshold[arg]

                    for arg in ("warn_time_period", "crit_time_period"):
                        if arg in threshold:
                            kwargs[arg] = Threshold.map_time_period_to_seconds(
                                threshold[arg]
                            )

                    # Create a threshold object
                    threshold = Threshold(**kwargs)
                    self.thresholds.append(threshold)

            # Load in the thresholds
        elif self.options.filesystem_override:
            logging.debug("Handling custom thresholds")
            for override in self.options.filesystem_override:
                # Pull out the useful info from the override (we know it matches the regex, as it passed the argparse check)
                kwargs = {}
                if match_ := re.match(FILESYSTEM_OVERRIDE_REGEX, override):
                    groups = match_.groups()
                    kwargs = {"id": groups[0], "ignore": groups[1]}
                    if len(groups) > 2:
                        kwargs["warn_threshold"] = groups[2]
                    if len(groups) > 3:
                        kwargs["crit_threshold"] = groups[3]
                    if len(groups) > 4:
                        kwargs["team"] = groups[4]
                    if len(groups) > 5:
                        kwargs["min_severity"] = groups[5]

                # Create a threshold object
                threshold = Threshold(**kwargs)
                self.thresholds.append(threshold)


def filesystem_override_type(
    arg_value: str, pat: re.Pattern = re.compile(FILESYSTEM_OVERRIDE_REGEX)
) -> str:
    """Validate the filesystem override argument.

    Args:
        arg_value (str): The argument value to validate
        pat (re.Pattern, optional): The regex pattern to use. Defaults to re.compile(FILESYSTEM_OVERRIDE_REGEX).

    Raises:
        argparse.ArgumentTypeError: If the argument does not match the regex

    Returns:
        str: The argument value
    """
    if not pat.match(arg_value):
        raise argparse.ArgumentTypeError(
            "Argument must match <FILESYSTEM>,[Y|N](,<low threshold>(,<high threshold>(,<team>(,<severity>))))"
        )
    return arg_value


if __name__ == "__main__":
    LinuxFilesystemMetrics()
