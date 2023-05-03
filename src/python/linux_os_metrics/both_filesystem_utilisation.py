#!/usr/bin/env python

import argparse
import json
import logging
import os
import re
import shutil

from sensu_plugin import SensuPluginCheck, Threshold

FILESYSTEM_OVERRIDE_REGEX = (
    r"^([^,]+?),([YN])(?:,(\d+)(?:,(\d+)(?:,([^,]+?)(?:,(Minor|Major|Crit))*)*)*)*$"
)


class LinuxFilesystemMetrics(SensuPluginCheck):
    def setup(self):
        # Setup is called with self.parser set and is responsible for setting up
        # self.options before the run method is called
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

    def run(self):
        if self.options.verbose:
            logging.getLogger().setLevel(logging.DEBUG)

        # this method is called to perform the actual check

        # self.check_name("my_awesome_check")  # defaults to class name

        # Load default thresholds
        # This script just has 1 set of thresholds by default - The warn percent and crit percent
        threshold = Threshold(
            warn_threshold=self.options.default_warn,
            crit_threshold=self.options.default_crit,
            min_severity=self.options.min_severity,
            team=self.options.default_team,
        )
        self.thresholds.append(threshold)

        # Handle any threshold overrides
        if os.path.exists(self.options.thresholds_file):
            with open(self.options.thresholds_file) as file:
                json_file = json.load(file)
                for threshold in json_file:
                    logging.debug(threshold)
                    # Create threshold object
                    kwargs = {"id": threshold["id"], "ignore": threshold["ignore"]}
                    if "warn_threshold" in threshold:
                        kwargs["warn_threshold"] = threshold["warn_threshold"]
                    if "crit_threshold" in threshold:
                        kwargs["crit_threshold"] = threshold["crit_threshold"]
                    if "team" in threshold:
                        kwargs["team"] = threshold["team"]
                    if "min_severity" in threshold:
                        kwargs["min_severity"] = threshold["min_severity"]

                    if "warn_time_period" in threshold:
                        # Convert time period to seconds
                        kwargs["warn_time_seconds"] = self.map_time_period_to_seconds(
                            threshold["warn_time_period"]
                        )
                    if "crit_time_period" in threshold:
                        # Convert time period to seconds
                        kwargs["crit_time_seconds"] = self.map_time_period_to_seconds(
                            threshold["crit_time_period"]
                        )

                    # Create a threshold object
                    threshold = Threshold(**kwargs)
                    self.thresholds.append(threshold)

            # Load in the thresholds
        elif self.options.filesystem_override:
            logging.debug("Handling custom thresholds")
            for override in self.options.filesystem_override:
                # Pull out the useful info from the override (we know it matches the regex, as it passed the argparse check)
                groups = re.match(FILESYSTEM_OVERRIDE_REGEX, override).groups()
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

        rc = 0
        result_message = "Check ran OK"

        with open("/proc/mounts", "r") as f:
            for line in f.readlines():
                _, mount_point, filesystem_type, _ = line.split(" ", maxsplit=3)
                if re.match(r"(ext[0-9]|zfs)", filesystem_type):
                    total, used, free = shutil.disk_usage(mount_point)
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


def filesystem_override_type(arg_value, pat=re.compile(FILESYSTEM_OVERRIDE_REGEX)):
    if not pat.match(arg_value):
        raise argparse.ArgumentTypeError(
            "Argument must match <FILESYSTEM>,[Y|N](,<low threshold>(,<high threshold>(,<team>(,<severity>))))"
        )
    return arg_value


if __name__ == "__main__":
    rc = LinuxFilesystemMetrics()
