#!/usr/bin/env python
"""Basic script to collect CPU metrics on Linux systems and generate alerts or metric output for Sensu.

This is compatible with Linux systems only (not MacOS or Windows), as it relies on the /proc filesystem and vmstat
"""
import argparse
import json
import logging
import os
import re
import textwrap

from sensu_plugin import EnvDefault, SensuPluginCheck, Threshold

CPU_OVERRIDE_REGEX = (
    r"(\d+)(%|core[s]*),(?:(\d+)([mh]))*,(\d+)*,(Minor|Major|Crit(?:ical))"
)
ALERT_TYPE_REGEX = re.compile(r"(\d+)(%|core[s]*)")


class LinuxCPUMetrics(SensuPluginCheck):
    """Class to collect CPU metrics on Linux systems and generate alerts or metric output for Sensu."""

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
            help=(
                "default warn threshold. This can be specified multiple times, and must"
                " match the CPU_OVERRIDE_REGEX detailed below"
            ),
            type=self._cpu_override_type,
            default=[],
            action="append",
        )

        self.parser.add_argument(
            "--default_crit",
            required=False,
            help=(
                "default critical threshold. This can be specified multiple times, and"
                " must match the CPU_OVERRIDE_REGEX detailed below"
            ),
            type=self._cpu_override_type,
            default=[],
            action="append",
        )

        self.parser.add_argument(
            "--min_severity",
            required=False,
            help=(
                "the lowest severity to alert at for the warn threshold. One of Minor,"
                " Major, Critical"
            ),
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
            envvar="SENSU_CPU_THRESHOLDS_FILE",
            action=EnvDefault,
        )

        self.parser.formatter_class = argparse.RawDescriptionHelpFormatter
        self.parser.description = textwrap.dedent(
            """
                IMPORTANT:
                The thresholds_file should be a JSON file containing a list of threshold overrides.

                If no thresholds_file is defined, and no default_warn or default_crit is defined, then no thresholds will be checked, and the check will always return OK
            """
        )
        self.parser.epilog = textwrap.dedent(
            f"""
                CPU_OVERRIDE_REGEX: {CPU_OVERRIDE_REGEX}
                Groups are:
                    1  - The threshold as an integer, this would either be the percentage value or the number of cores
                    2  - The threshold type, either % or core(s)
                    3  - The time value, this is optional. This is the number of minutes or hours (given by m or h as the next group) before the alert is triggered if the threshold is exceeded
                    4  - The time period, this is optional. This is either m or s, and indicates whether the time value is in minutes or hours
                    5  - The number of occurrences, this is optional. This is the number of times the threshold must be exceeded before the alert is triggered
                    6  - The severity. This is the severity of the alert, and can be one of Minor, Major, Critical

                Example thresholds:
                    90%,,,Minor - Warn at 90% CPU usage
                    90%,1h,,Minor - Warn at 90% CPU usage, if the threshold is exceeded for 1 hour
                    6cores,5m,,Major - Warn if the CPU usage is more than 6 cores, if the threshold is exceeded for 5 minutes
                    90%,,10,Minor - Warn at 90% CPU usage, if the threshold is exceeded 10 times
            """
        )

    def run(self) -> None:
        """Run the actual check."""
        if self.options.verbose:
            logging.getLogger().setLevel(logging.DEBUG)

        # Load default thresholds
        # This script just has 1 set of thresholds by default - The warn percent and crit percent
        # We need to parse the default_warn and default_crit thresholds so we can create the Threshold object

        for threshold in self.options.default_warn:
            self._process_thresholds("warn", threshold)

        for threshold in self.options.default_crit:
            self._process_thresholds("crit", threshold)

        self._process_thresholds_file()

        rc = 0
        result_message = "Check ran OK"

        # Get CPU usage
        # This returns the number of processors, followed by CPU usage in percent overall
        command = (
            "cat /proc/cpuinfo | egrep 'processor.*: [0-9]+' | tail -1; vmstat 5 2 |"
            " tail -1 | awk '{print $1,$13,$14,$15,$16'}"
        )
        stream = os.popen(command)
        output = stream.read()

        # Split the output into 2 lines
        lines = output.split("\n")
        processor_count = int(lines[0].split(": ")[1]) + 1
        cpu_stats = lines[1].split(" ")

        cpu_used_percent = 100 - int(cpu_stats[3])
        cpu_cores_used = (cpu_used_percent / 100) * processor_count

        if not self.options.check_only or self.options.metrics_only:
            self.output_metrics(["os.cpu.cores_used", cpu_cores_used])
            self.output_metrics(["os.cpu.run_queue", int(cpu_stats[0])])
            self.output_metrics(["os.cpu.percent_user", int(cpu_stats[1])])
            self.output_metrics(["os.cpu.percent_system", int(cpu_stats[2])])
            self.output_metrics(["os.cpu.percent_idle", int(cpu_stats[3])])
            self.output_metrics(["os.cpu.percent_wait", int(cpu_stats[4])])

        if not self.options.metrics_only or self.options.check_only:
            # Process % usage thresholds first
            threshold_result = self.process_value(
                None,
                cpu_used_percent,
                ok_message=f"CPU utilisation is OK ({cpu_used_percent:.0f}% used)",
                alert_message=(
                    "CPU utilisation is > ::THRESHOLD::::ALERT_TYPE::::PERIOD::"
                    f" ({cpu_used_percent:.0f}% used)"
                ),
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
                alert_message=(
                    "CPU utilisation is > ::THRESHOLD:: ::ALERT_TYPE::::PERIOD::"
                    f" ({cpu_cores_used:.0f} ::ALERT_TYPE:: used)"
                ),
                alert_type="cores",
            )
            result_message, rc1 = self.process_output_and_rc(
                threshold_result, result_message, "CPU utilisation is high"
            )
            if rc1 > rc:
                rc = rc1

        self.return_final_output(rc, result_message)

    def _process_thresholds_file(self) -> None:
        # Handle anything in the thresholds file
        if os.path.exists(self.options.thresholds_file):
            with open(self.options.thresholds_file, encoding="utf-8") as file:
                json_file = json.load(file)
                for threshold in json_file:
                    logging.debug(threshold)
                    # Create threshold object
                    kwargs = {}
                    metadata = {}

                    for arg in ("warn_threshold", "crit_threshold"):
                        if match_ := ALERT_TYPE_REGEX.match(threshold[arg]):
                            kwargs[arg] = match_.groups()[0]
                            metadata["alert_type"] = match_.groups()[1]

                    if "team" in threshold:
                        kwargs["team"] = threshold["team"]
                    if "min_severity" in threshold:
                        kwargs["min_severity"] = threshold["min_severity"]

                    for arg in ("warn_time_period", "crit_time_period"):
                        if arg in threshold:
                            kwargs[arg] = Threshold.map_time_period_to_seconds(
                                threshold[arg]
                            )

                    if "warn_occurrences" in threshold:
                        kwargs["warn_occurrences"] = threshold["warn_occurrences"]
                    if "crit_occurrences" in threshold:
                        kwargs["crit_occurrences"] = threshold["crit_occurrences"]

                    if "exclude_times" in threshold:
                        kwargs["exclude_times"] = threshold["exclude_times"]

                    kwargs["metadata"] = metadata

                    # Create a threshold object
                    threshold = Threshold(**kwargs)  # type: ignore[arg-type]
                    self.thresholds.append(threshold)

    def _process_thresholds(self, threshold_level: str, override_line: str) -> None:
        """Process any thresholds for the specified threshold level and create the appropriate Threshold objects."""
        matches = (
            re.findall(CPU_OVERRIDE_REGEX, override_line)
            if self.options.default_warn
            else []
        )
        for groups in matches:
            value = groups[0]
            alert_type = groups[1]
            time = groups[2]
            time_period = groups[3] if groups[3] else ""
            occurrences = groups[4] if groups[4] else 0
            severity = groups[5]

            time_seconds = 0
            if time_period == "h":
                time_seconds = int(time) * 60 * 60
            elif time_period == "m":
                time_seconds = int(time) * 60

            metadata = {}
            metadata["alert_type"] = alert_type

            if threshold_level == "warn":
                threshold = Threshold(
                    warn_threshold=value,
                    min_severity=severity,
                    team=self.options.default_team,
                    warn_time_seconds=time_seconds,
                    crit_occurrences=occurrences,
                    metadata=metadata,
                )
            else:
                threshold = Threshold(
                    crit_threshold=value,
                    min_severity=severity,
                    team=self.options.default_team,
                    crit_time_seconds=time_seconds,
                    crit_occurrences=occurrences,
                    metadata=metadata,
                )

            self.thresholds.append(threshold)

    def _cpu_override_type(
        self, arg_value: str, pat: re.Pattern = re.compile(CPU_OVERRIDE_REGEX)
    ) -> str:
        if not pat.match(arg_value):
            raise argparse.ArgumentTypeError(
                f"Argument must match {CPU_OVERRIDE_REGEX}"
            )
        return arg_value


if __name__ == "__main__":
    LinuxCPUMetrics()
