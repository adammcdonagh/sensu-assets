#!/usr/bin/env python

import argparse
import json
import logging
import os
import re

from sensu_plugin import SensuPluginCheck, Threshold

CPU_OVERRIDE_REGEX = r"(\d+)(%|core[s]*),(\d+)([mh]),(Minor|Major|Crit(?:ical))"
ALERT_TYPE_REGEX = re.compile(r"(\d+)(%|core[s]*)")


class LinuxCPUMetrics(SensuPluginCheck):
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
            help="default warn threshold",
            type=cpu_override_type,
            default=None,
        )

        self.parser.add_argument(
            "--default_crit",
            required=False,
            help="default critical threshold",
            type=cpu_override_type,
            default=None,
        )

        self.parser.add_argument(
            "--min_severity",
            required=False,
            help="the lowest severity to alert at for the warn threshold",
            type=str,
            default="Minor",
        )

        self.parser.add_argument(
            "--default_team",
            required=False,
            help="the default team that alert should go to",
            type=str,
            default=None,
        )

        self.parser.add_argument(
            "--thresholds_file",
            required=False,
            help="JSON file containing threshold overrides to use",
            type=str,
            default="/var/cache/sensu/sensu-agent/cpu.json",
        )

    def run(self):
        if self.options.verbose:
            logging.getLogger().setLevel(logging.DEBUG)

        # Load default thresholds
        # This script just has 1 set of thresholds by default - The warn percent and crit percent
        # We need to parse the default_warn and default_crit thresholds so we can create the Threshold object

        # Parse the default_warn threshold
        matches = (
            re.findall(CPU_OVERRIDE_REGEX, self.options.default_warn)
            if self.options.default_warn
            else []
        )
        for groups in matches:
            warn_value = groups[0]
            alert_type = groups[1]
            warn_time = groups[2]
            warn_time_period = groups[3]
            warn_severity = groups[4]

            warn_time_seconds = 0
            if warn_time_period == "h":
                warn_time_seconds = int(warn_time) * 60 * 60
            elif warn_time_period == "m":
                warn_time_seconds = int(warn_time) * 60

            metadata = dict()
            metadata["alert_type"] = alert_type

            threshold = Threshold(
                warn_threshold=warn_value,
                min_severity=warn_severity,
                team=self.options.default_team,
                warn_time_seconds=warn_time_seconds,
                metadata=metadata,
            )

            self.thresholds.append(threshold)

        matches = (
            re.findall(CPU_OVERRIDE_REGEX, self.options.default_crit)
            if self.options.default_crit
            else []
        )
        for groups in matches:
            crit_value = groups[0]
            alert_type = groups[1]
            crit_time = groups[2]
            crit_time_period = groups[3]
            crit_severity = groups[4]

            crit_time_seconds = 0
            if crit_time_period == "h":
                crit_time_seconds = int(crit_time) * 60 * 60
            elif crit_time_period == "m":
                crit_time_seconds = int(crit_time) * 60

            metadata = dict()
            metadata["alert_type"] = alert_type

            threshold = Threshold(
                crit_threshold=crit_value,
                min_severity=crit_severity,
                team=self.options.default_team,
                crit_time_seconds=crit_time_seconds,
                metadata=metadata,
            )

            self.thresholds.append(threshold)

        # Handle any threshold overrides
        if os.path.exists(self.options.thresholds_file):
            with open(self.options.thresholds_file) as file:
                json_file = json.load(file)
                for threshold in json_file:
                    logging.debug(threshold)
                    # Create threshold object
                    kwargs = {}
                    metadata = dict()

                    if "warn_threshold" in threshold:
                        groups = ALERT_TYPE_REGEX.match(
                            threshold["warn_threshold"]
                        ).groups()
                        kwargs["warn_threshold"] = groups[0]
                        metadata["alert_type"] = groups[1]
                    if "crit_threshold" in threshold:
                        groups = ALERT_TYPE_REGEX.match(
                            threshold["crit_threshold"]
                        ).groups()
                        kwargs["crit_threshold"] = groups[0]
                        metadata["alert_type"] = groups[1]

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

                    if "warn_occurrences" in threshold:
                        kwargs["warn_occurrences"] = threshold["warn_occurrences"]
                    if "crit_occurrences" in threshold:
                        kwargs["crit_occurrences"] = threshold["crit_occurrences"]

                    if "exclude_times" in threshold:
                        kwargs["exclude_times"] = threshold["exclude_times"]

                    kwargs["metadata"] = metadata

                    # Create a threshold object
                    threshold = Threshold(**kwargs)
                    self.thresholds.append(threshold)

        rc = 0
        result_message = "Check ran OK"

        # Get CPU usage
        # This returns the number of processors, followed by CPU usage in percent overall
        command = "cat /proc/cpuinfo | egrep  'processor.*: [0-9]+' | tail -1; vmstat 5 2 | tail -1 | awk '{print $1,$13,$14,$15,$16'}"  # noqa: FS003
        stream = os.popen(command)
        output = stream.read()

        # Split the output into 2 lines
        lines = output.split("\n")
        processor_count = int(lines[0].split(": ")[1]) + 1
        cpu_stats = lines[1].split(" ")
        cpu_run_queue = int(cpu_stats[0])
        cpu_user_percent = int(cpu_stats[1])
        cpu_system_percent = int(cpu_stats[2])
        cpu_idle_percent = int(cpu_stats[3])
        cpu_iowait_percent = int(cpu_stats[4])

        cpu_used_percent = 100 - cpu_idle_percent
        cpu_cores_used = (cpu_used_percent / 100) * processor_count

        if not self.options.check_only or self.options.metrics_only:
            self.output_metrics(["os.cpu.cores_used", cpu_cores_used])
            self.output_metrics(["os.cpu.run_queue", cpu_run_queue])
            self.output_metrics(["os.cpu.percent_user", cpu_user_percent])
            self.output_metrics(["os.cpu.percent_system", cpu_system_percent])
            self.output_metrics(["os.cpu.percent_idle", cpu_idle_percent])
            self.output_metrics(["os.cpu.percent_wait", cpu_iowait_percent])

        if not self.options.metrics_only or self.options.check_only:
            # Process % usage thresholds first
            threshold_result = self.process_value(
                None,
                cpu_used_percent,
                ok_message=f"CPU utilisation is OK ({cpu_used_percent:.0f}% used)",
                alert_message=f"CPU utilisation is > ::THRESHOLD::::ALERT_TYPE:: for ::PERIOD:: ({cpu_used_percent:.0f}% used)",
                alert_type="%",
            )
            result_message, rc = self.process_output_and_rc(
                threshold_result, result_message, "CPU utilisation is high"
            )

            # And then the core count
            threshold_result = self.process_value(
                None,
                cpu_cores_used,
                ok_message=f"CPU utilisation is OK ({cpu_used_percent:.0f}% used)",
                alert_message=f"CPU utilisation is > ::THRESHOLD:: ::ALERT_TYPE:: for ::PERIOD:: ({cpu_cores_used:.0f} ::ALERT_TYPE:: used)",
                alert_type="cores",
            )
            result_message, rc1 = self.process_output_and_rc(
                threshold_result, result_message, "CPU utilisation is high"
            )
            if rc1 > rc:
                rc = rc1

        self.return_final_output(rc, result_message)


def cpu_override_type(arg_value, pat=re.compile(CPU_OVERRIDE_REGEX)):
    if not pat.match(arg_value):
        raise argparse.ArgumentTypeError(
            "Argument must match <X%|Xcore[s]>,[Y[hm]],<severity>"
        )
    return arg_value


if __name__ == "__main__":
    rc = LinuxCPUMetrics()
