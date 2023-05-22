#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Helper module to define Sensu thresholds and threshold results."""
import datetime as dt
import json
import operator
import os
import re
import time
from dataclasses import dataclass, field
from typing import Pattern

import humanize
from sensu_plugin import init_logging
from sensu_plugin.check_result import CheckResultMetadata

logger = init_logging(__name__)
TIME_PERIOD_REGEX: Pattern = re.compile(r"(\d+)(h|m)")


@dataclass
class ThresholdResult:
    """A class to represent a Sensu threshold result.

    This class is used to store the results of a threshold check, and it's return code.

    Args:
        rc (int): The return code for this threshold check
        result_messages (list): A list of messages to return for this threshold check
    """

    rc: int
    result_messages: list = field(default_factory=list)


@dataclass
class Threshold:  # noqa: PLR902
    """A class to represent a Sensu threshold.

    This generic class can be used to define complex thresholds, ranging from a simple
    >= check to a complex check that requires multiple occurrences and time windows.

    Args:
        id (str): The unique ID of the threshold for this check
        warn_threshold (int): The warning threshold for this check
        crit_threshold (int): The critical threshold for this check
        team (str): The team responsible for this check
        min_severity (str): The minimum severity for this check whenb breaching it's lowest threshold
        metadata (dict): Any metadata for this check
        ignore (bool): Whether or not to ignore this threshold, used when a specific id is to be ignored. e.g. "/swap"
        warn_time_seconds (int): The time window in seconds for the warning threshold before the alert is triggered
        crit_time_seconds (int): The time window in seconds for the critical threshold before the alert is triggered
        warn_occurrences (int): The number of occurrences for the warning threshold before the alert is triggered
        crit_occurrences (int): The number of occurrences for the critical threshold before the alert is triggered
        operator (str): The operator to use for the comparison, defaults to ">="
    """

    id: str = None  # noqa: PLC103
    warn_threshold: int = None
    crit_threshold: int = None
    team: str = None
    min_severity: str = "Minor"
    metadata: dict = None
    ignore: bool = False
    warn_time_seconds: int = None
    crit_time_seconds: int = None
    warn_occurrences: int = None
    crit_occurrences: int = None
    operator: str = ">="
    exclude_times: list = None

    # Validate the operator when the class is created
    def __post_init__(self) -> None:
        """Post init method for the Threshold class.

        Sets up the logger and validates the operator.
        """
        self.logger = init_logging(__name__)

        # Check that the operator is valid
        if self.operator not in [">=", "<=", ">", "<"]:
            raise ValueError("Invalid operator, must be >=, <= , > or <")

    def next_severity(self) -> str:
        """Return the next severity for this threshold."""
        if re.match(r"^Minor$", self.min_severity, re.IGNORECASE):
            return "Major"
        if re.match(r"^(Major|Crit(ical)*)$", self.min_severity, re.IGNORECASE):
            return "Critical"

        return "Unknown"

    def evaluate_threshold(  # noqa: PLR914 # for the sake of readability
        self,
        threshold_id: int,
        current_value: int | str,
        check_result_metadata: CheckResultMetadata,
    ) -> ThresholdResult:
        """Evaluate a threshold.

        This method does the majority of the work. It checks whether each threshold is breached, and
        if so populates the output message and return code.

        Args:
            threshold_id (int): The ID of the threshold to evaluate
            current_value (int|str): The current value to compare against the threshold
            check_result_metadata (CheckResultMetadata): The check result metadata object

        Returns:
            ThresholdResult: The result of the threshold check
        """
        result = ThresholdResult(0)

        # If the threshold is set to ignore, then just return here with no output
        if self.ignore:
            logger.debug("Skipping due to ignore")
            return None

        # Now do the actual threshold checking

        # Load the alert cache, if one exists
        self._load_alert_cache(check_result_metadata, threshold_id)

        # Check whether we're within an exclusion time period which would prevent us from alerting
        exclusion_active = self._is_in_exclusion_time()

        thresholds = ["crit", "warn"]
        has_output = False
        rc = 0

        check_name = re.sub(r"[^a-zA-Z0-9\._]", "", check_result_metadata.check_name)
        state_file = f"{check_result_metadata.state_file_dir}/alert_status_cache/{check_name}_threshold_{threshold_id}"

        ok_message = check_result_metadata.ok_message
        warn_message = check_result_metadata.warn_message
        crit_message = check_result_metadata.crit_message
        alert_type = check_result_metadata.alert_type

        # Default OK output
        result_output = {
            "message": ok_message,
            "alert_key": (check_result_metadata.alert_id or threshold_id),
            "team": self.team,
        }

        # Loop through the critical and warning thresholds
        if exclusion_active:
            result.result_messages.append(result_output)
            result.rc = 0
            return result

        for threshold in thresholds:
            # Initialise some important values based on the threshold severity we're checking (warn|crit)
            (
                valid_threshold,
                threshold_limit,
                delta,
                message,
                severity,
                alert_time,
                occurrences,
            ) = self._populate_threshold_values(threshold, crit_message, warn_message)

            if not valid_threshold:
                continue

            ok_message = ok_message.format(
                THRESHOLD=threshold_limit,
                ALERT_TYPE=alert_type,
            )

            operator_ = self.map_operator_to_function(self.operator)
            logger.debug(
                f"Comparing: {current_value} {operator_.__name__} {threshold_limit}"
            )

            is_advanced_threshold = not (not occurrences and not alert_time)
            if threshold_limit and operator_(current_value, threshold_limit):
                # We've breached the threshold
                logger.debug(f"Over {threshold} threshold")
                period = (
                    f" for {humanize.precisedelta(delta, minimum_unit='minutes')}"
                    if alert_time
                    else ""
                )

                # Populate the message with the correct values for this threshold
                message = message.format(
                    THRESHOLD=threshold_limit,
                    ALERT_TYPE=alert_type,
                    PERIOD=f"{period}",
                )

                # Handle output for this threshold
                # This determines whether or not to suppress output, or to append output to the result
                (suppress_alert, has_output) = self._handle_threshold_output(
                    has_output,
                    threshold,
                    threshold_id,
                    check_result_metadata.alert_id,
                    message,
                    severity,
                    alert_time,
                    occurrences,
                    period,
                    result.result_messages,
                )

                if is_advanced_threshold:
                    # Now we've checked the warn and crit thresholds
                    # Write the status to the cache file
                    # Append/Update/Create threshold.metadata["alert_cache"]
                    # If there's no existing cache entry, create one
                    self._handle_advanced_threshold_cache(
                        threshold, threshold_id, state_file
                    )

                # Set the appropriate return code based on the severity
                if not suppress_alert:
                    if severity == "Critical":
                        rc = 2
                    elif rc < 2:
                        rc = 1

            # If the threshold isn't breached, we need to make sure it's not in the cache
            elif is_advanced_threshold:
                self._remove_advanced_threshold_from_cache(
                    threshold, threshold_id, state_file
                )

        if not has_output:
            logger.debug("Threshold is OK")
            logger.debug(f"Adding output line: {result_output}")
            result.result_messages.append(result_output)

        if rc > result.rc:
            result.rc = rc

        return result

    def _load_alert_cache(
        self, check_result_metadata: CheckResultMetadata, threshold_id: int
    ) -> None:
        if (
            self.warn_time_seconds
            or self.crit_time_seconds
            or self.warn_occurrences
            or self.crit_occurrences
        ):
            state_file_dir = check_result_metadata.state_file_dir
            # Determine if there's already a cache file indicating a previous breach
            file_pattern = re.sub(
                r"[^a-zA-Z0-9\._]", "", check_result_metadata.check_name
            )
            file_pattern = rf"{file_pattern}_threshold_(\d*)$"
            if os.path.exists(state_file_dir):
                for file in os.listdir(state_file_dir):
                    if re.match(file_pattern, file):
                        threshold_no = int(re.match(file_pattern, file)[1])
                        if "alert_cache" not in self.metadata:
                            self.metadata["alert_cache"] = []

                        if threshold_no == threshold_id:
                            with open(
                                f"{state_file_dir}/{file}", "r", encoding="utf-8"
                            ) as file_:
                                self.metadata["alert_cache"] = json.load(file_)

    def _is_in_exclusion_time(self) -> bool:
        if self.exclude_times:
            # Loop through each exclusion time, parse it and determine if we're within the time period
            for exclude_time in self.exclude_times:
                self.logger.debug(f"Checking time based exclusion: {exclude_time}")
                # Check if we're in one of the days of the week, or if none specified then aply to all days
                is_current_day = False
                if "days_of_week" in exclude_time:
                    for day in exclude_time["days_of_week"]:
                        if day == dt.datetime.now().strftime("%A"):
                            is_current_day = True
                            break
                else:
                    is_current_day = True

                if not is_current_day:
                    self.logger.debug("Ignoring time exclusion as its not for today")
                    continue

                # Parse the time
                exclude_time_start = dt.datetime.strptime(
                    exclude_time["start_time"], "%H:%M"
                ).time()
                exclude_time_end = dt.datetime.strptime(
                    exclude_time["end_time"], "%H:%M"
                ).time()

                # Determine if we're within the time period
                if exclude_time_start <= dt.datetime.now().time() <= exclude_time_end:
                    self.logger.debug("Skipping threshold check due to exclude time")
                    return True

                self.logger.debug("Ignoring time exclusion as not within time window")
            return False
        return False

    def _populate_threshold_values(
        self, threshold, crit_message, warn_message
    ) -> tuple:
        """Populate the threshold values.

        Args:
            threshold (str): The threshold type - warn or crit.
            crit_message (str): The critical message to populate.
            warn_message (str): The warning message to populate.


        Returns:
            tuple: The populated threshold values for the threshold type.

        The first value in the dict determines whether the given threshold is valid or not.
        """
        (threshold_limit, delta, message, severity, alert_time, occurrences) = (
            None,
        ) * 6

        if threshold == "crit" and self.crit_threshold:
            threshold_limit = float(self.crit_threshold)
            if self.crit_time_seconds:
                delta = dt.timedelta(seconds=self.crit_time_seconds)
            message = crit_message
            severity = self.next_severity()
            alert_time = self.crit_time_seconds
            occurrences = self.crit_occurrences
        elif threshold == "warn" and self.warn_threshold:
            threshold_limit = float(self.warn_threshold)
            if self.warn_time_seconds:
                delta = dt.timedelta(seconds=self.warn_time_seconds)
            message = warn_message
            severity = self.min_severity
            # Amount of time in seconds the threshold can be breached before we actually generate an alert
            alert_time = self.warn_time_seconds
            # Number of times the threshold can be breached before we actually generate an alert
            occurrences = self.warn_occurrences
        else:
            return (False, None, None, None, None, None, None)

        return (
            True,
            threshold_limit,
            delta,
            message,
            severity,
            alert_time,
            occurrences,
        )

    def _handle_threshold_output(  # noqa: PLR912, PLR913, PLR914
        self,
        has_output: bool,
        threshold: str,
        threshold_id: int,
        alert_id: str,
        message: str,
        severity: str,
        alert_time: int,
        occurrences: int,
        period: int,
        result_messages: list,
    ) -> tuple:
        # Only allow one output per threshold
        suppress_alert = False
        if not has_output:  # noqa: PLR702
            #  Now check for any occurrence or time based conditions before outputting
            first_occurrence = True
            if self.metadata and "alert_cache" in self.metadata:
                # Loop through each instance of a previous alert to check if the threshold_no matches

                for alert_instance in self.metadata["alert_cache"]:
                    if (
                        alert_instance["threshold_no"] == threshold_id
                        and alert_instance["threshold_type"] == threshold
                    ):
                        first_occurrence = False
                        # Determine whether to alert or not based on whether we're checking occurrences or time since first breach
                        if occurrences:
                            if alert_instance["occurrences"] + 1 <= occurrences:
                                suppress_alert = True
                            logger.debug(
                                f"Threshold has been breached {alert_instance['occurrences'] + 1} times - Allowed {occurrences} before alerting. {'Suppressing alert.' if suppress_alert else ''}"
                            )
                        if alert_time:
                            time_since_breach_started = (
                                time.time() - alert_instance["exceeding_start"]
                            )
                            if time_since_breach_started < alert_time:
                                suppress_alert = True
                            logger.debug(
                                f"Threshold has been breached for {humanize.precisedelta(dt.timedelta(seconds=time_since_breach_started), minimum_unit='minutes')} - Allowed {period} before alerting. {'Suppressing alert.' if suppress_alert else ''}"
                            )
                        break
            else:
                logger.debug("No alert cache")
            if first_occurrence:
                # We've not breached before, so check to see if we are breaching now or not
                if occurrences and occurrences > 1:
                    logger.debug(
                        f"Threshold has been breached for the first time - Allowed {occurrences} before alerting. Suppressing alert."
                    )
                    suppress_alert = True
                if alert_time:
                    logger.debug(
                        f"Threshold has been breached for the first time - Allowed {period} before alerting. Suppressing alert."
                    )
                    suppress_alert = True

            if not suppress_alert:
                result_output = {
                    "message": message,
                    "alert_key": (alert_id or threshold_id),
                    "severity": severity,
                    "team": self.team,
                }
                logger.debug(f"Adding output line: {result_output}")
                result_messages.append(result_output)

                has_output = True
        return (suppress_alert, has_output)

    def _handle_advanced_threshold_cache(
        self, threshold: str, threshold_id: int, state_file: str
    ) -> None:
        alert_instance = {}
        if "alert_cache" not in self.metadata:
            alert_instance = {
                "threshold_type": threshold,
                "threshold_no": threshold_id,
                "exceeding_start": time.time(),
                "occurrences": 1,
            }
            self.metadata["alert_cache"] = [alert_instance]
        else:
            # Find the existing cache entry and update it
            # or create a new one if there's nothing for this threshold type
            found_cache_entry = False
            for alert_instance_1 in self.metadata["alert_cache"]:
                if (
                    alert_instance_1["threshold_no"] == threshold_id
                    and alert_instance_1["threshold_type"] == threshold
                ):
                    alert_instance_1["occurrences"] += 1
                    alert_instance = alert_instance_1
                    found_cache_entry = True
                    break

            if not found_cache_entry:
                alert_instance = {
                    "threshold_type": threshold,
                    "threshold_no": threshold_id,
                    "exceeding_start": time.time(),
                    "occurrences": 1,
                }
                self.metadata["alert_cache"].append(alert_instance)

        os.makedirs(os.path.dirname(state_file), exist_ok=True)
        with open(state_file, "w", encoding="utf-8") as file_:
            json.dump(self.metadata["alert_cache"], file_)

    def _remove_advanced_threshold_from_cache(
        self, threshold: str, threshold_id: int, state_file: str
    ) -> None:
        # Loop through the alert_cache to see if this alert instance exists
        # If it does, remove it
        cache_needs_update = False
        if "alert_cache" in self.metadata:
            for alert_instance_2 in self.metadata["alert_cache"]:
                if (
                    alert_instance_2["threshold_no"] == threshold_id
                    and alert_instance_2["threshold_type"] == threshold
                ):
                    self.metadata["alert_cache"].remove(alert_instance_2)
                    logger.debug("Removed alert instance from cache")
                    cache_needs_update = True
                    break
        # If we made a change, then we need to write the JSON file again
        if cache_needs_update:
            with open(state_file, "w", encoding="utf-8") as file_:
                json.dump(self.metadata["alert_cache"], file_)

    def map_operator_to_function(self, operator_: str) -> callable:
        """Map the operator string to the correct function.

        Args:
            operator_ (str): The operator to map.

        Returns:
            callable: The function that corresponds to the operator.
        """
        symbol_name_map = {
            ">=": operator.ge,
            "<=": operator.le,
            ">": operator.gt,
            "<": operator.lt,
            "==": operator.eq,
            "!=": operator.ne,
        }
        return symbol_name_map[operator_]

    def map_time_period_to_seconds(self, time_period: str) -> int:
        """Map the time period string to the number of seconds.

        Args:
            time_period (str): The time period to map.

        Returns:
            int: The number of seconds that corresponds to the time period.
        """
        groups = TIME_PERIOD_REGEX.match(time_period).groups()
        return int(groups[0]) * 60 * 60 if groups[1] == "h" else int(groups[0]) * 60
