#!/usr/bin/env python
# -*- coding: utf-8 -*-
import datetime as dt
import json
import logging
import operator
import os
import re
import time

import humanize
from sensu_plugin.plugin import SensuPlugin
from sensu_plugin.threshold import ThresholdResult


class SensuPluginCheck(SensuPlugin):
    """
    Class that inherits from SensuPlugin.
    """

    TIME_PERIOD_REGEX = re.compile(r"(\d+)(h|m)")

    def __init__(self, thresholds=None, autorun=True):
        self.thresholds = thresholds or []

        SensuPlugin.__init__(self, autorun)

    def check_name(self, name=None):
        """
        Checks the plugin name and sets it accordingly.
        Uses name if specified, class name if not set.
        """
        if name:
            self.plugin_info["check_name"] = name

        if self.plugin_info["check_name"] is not None:
            return self.plugin_info["check_name"]

        return self.__class__.__name__

    def message(self, *m):
        self.plugin_info["message"] = m

    def output(self, args, alert_key=None, severity=None, team=None, source=None):
        msg = ""
        if args is not None and not (args[0] is None and len(args) == 1):
            msg = f": {' '.join(str(message) for message in args)}"
        else:
            msg = self.plugin_info["message"]

        # Default to OK
        self.plugin_info["status"] = "OK"
        if severity and not re.match(r"^Minor", severity, re.IGNORECASE):
            self.plugin_info["status"] = "CRITICAL"
        elif severity:
            self.plugin_info["status"] = "WARN"

        alert_key = f"KEY:{alert_key} " if alert_key else ""
        severity_msg = f"SEV:{severity} " if severity else ""
        team_msg = f"TEAM:{team} " if team else ""
        source_msg = f"SOURCE:{source} " if source else ""

        end_text = (
            f" | {alert_key}{severity_msg}{team_msg}{source_msg}"
            if (alert_key or severity_msg or team_msg or source_msg)
            else ""
        )
        output_text = f"{self.check_name()} {self.plugin_info['status']}{msg}{end_text}"

        print(output_text)

    def return_final_output(self, rc, result_message):
        if rc == 0:
            self.ok(result_message, exit=True)
        elif rc == 1:
            self.warning(result_message, exit=True)
        elif rc == 2:
            self.critical(result_message, exit=True)
        else:
            self.unknown("Unknown state returned", exit=True)

    def process_value(
        self,
        id,
        current_value,
        ok_message,
        alert_message=None,
        warn_message=None,
        crit_message=None,
        alert_type=None,
    ):
        """
        Process numeric threshold results
        """
        result = ThresholdResult(0)

        # Ensure we have all args we need
        if not ok_message:
            raise Exception(
                "No ok_message passed. Please ensure correct invocation of process_value function"
            )
        if not alert_message and not warn_message and not crit_message:
            raise Exception(
                "No alert level message passed. Please ensure correct invocation of process_value function. At least one alert level message is required"
            )

        ok_message = re.sub(r"::(\w+?)::", r"{\1}", ok_message)
        alert_message = re.sub(r"::(\w+?)::", r"{\1}", alert_message)
        if warn_message:
            re.sub(r"::(\w+?)::", r"{\1}", warn_message)
        if crit_message:
            re.sub(r"::(\w+?)::", r"{\1}", crit_message)

        logging.debug(
            f"Checking thresholds for key: {id} - With current value of {current_value}"
        )

        # Look for a threshold with a matching ID
        matching_thresholds = []
        default_threshold = None

        # ID specific thesholds
        if id:
            for threshold in self.thresholds:
                # If we found a threshold for this ID then save it and break
                if threshold.id == id:
                    matching_thresholds.append(threshold)
                    break

                # If we havent found a specific threshold, but we found the default one
                # save it, incase we need dont find a specific one at all
                if not threshold.id:
                    default_threshold = threshold

            # If we didn't find a specific threshold, then we need to use the default
            if not matching_thresholds:
                matching_thresholds.append(default_threshold)

        elif alert_type:
            for threshold in self.thresholds:
                if (
                    threshold.metadata
                    and "alert_type" in threshold.metadata
                    and threshold.metadata["alert_type"] == alert_type
                ):
                    matching_thresholds.append(threshold)
        else:
            matching_thresholds = self.thresholds

        # Loop through each threshold
        threshold_id = 1
        for matching_threshold in matching_thresholds:
            logging.debug(f"Using threshold: {matching_threshold}")

            # Determine what message to use for output
            # Warning level message
            if not warn_message:
                warn_message = alert_message

            # Warning level message
            if not crit_message:
                crit_message = alert_message

            # If the threshold is set to ignore, then just return here with no output
            if matching_threshold.ignore:
                logging.debug("Skipping due to ignore")
                return None

            # Now do the actual threshold checking
            status_file_dir = f"{self.SENSU_CACHE_DIR}/alert_status_cache"

            # Check whether this is an X in Y threshold and determine whether we are already inside, or
            # if this ocurrence will trigger that
            if (
                matching_threshold.warn_time_seconds
                or matching_threshold.crit_time_seconds
                or matching_threshold.warn_occurrences
                or matching_threshold.crit_occurrences
            ):
                # Determine if there's already a cache file indicating a previous breach
                file_pattern = re.sub(r"[^a-zA-Z0-9\._]", "", self.check_name())
                file_pattern = rf"{file_pattern}_threshold_(\d*)$"
                if os.path.exists(status_file_dir):
                    for file in os.listdir(status_file_dir):
                        if re.match(file_pattern, file):
                            threshold_no = int(re.match(file_pattern, file)[1])
                            if "alert_cache" not in matching_threshold.metadata:
                                matching_threshold.metadata["alert_cache"] = []

                            if threshold_no == threshold_id:
                                matching_threshold.metadata["alert_cache"] = json.load(
                                    open(f"{status_file_dir}/{file}", "r")
                                )

            exclusion_active = False
            is_in_exlusion_time = False
            if matching_threshold.exclude_times:
                # Loop through each exclusion time, parse it and determine if we're within the time period
                for exclude_time in matching_threshold.exclude_times:
                    logging.debug(f"Checking time based exclusion: {exclude_time}")
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
                        logging.debug("Ignoring time exclusion as its not for today")
                        continue

                    # Parse the time
                    exclude_time_start = dt.datetime.strptime(
                        exclude_time["start_time"], "%H:%M"
                    ).time()
                    exclude_time_end = dt.datetime.strptime(
                        exclude_time["end_time"], "%H:%M"
                    ).time()

                    # Determine if we're within the time period
                    if (
                        exclude_time_start
                        <= dt.datetime.now().time()
                        <= exclude_time_end
                    ):
                        logging.debug("Skipping threshold check due to exclude time")
                        is_in_exlusion_time = True
                    else:
                        logging.debug(
                            "Ignoring time exclusion as not within time window"
                        )

            if is_in_exlusion_time:
                exclusion_active = True

            # Check whether the threshold is actually breached
            thresholds = ["crit", "warn"]
            has_output = False
            rc = 0

            check_name = re.sub(r"[^a-zA-Z0-9\._]", "", self.check_name())
            state_file = f"{status_file_dir}/{check_name}_threshold_{threshold_id}"

            # Loop through the critical and warning thresholds
            if not exclusion_active:
                for threshold in thresholds:
                    (threshold_limit, delta, message, severity) = (None,) * 4
                    if threshold == "crit" and matching_threshold.crit_threshold:
                        threshold_limit = float(matching_threshold.crit_threshold)
                        if matching_threshold.crit_time_seconds:
                            delta = dt.timedelta(
                                seconds=matching_threshold.crit_time_seconds
                            )
                        message = crit_message
                        severity = matching_threshold.next_severity()
                        alert_time = matching_threshold.crit_time_seconds
                        occurrences = matching_threshold.crit_occurrences
                    elif threshold == "warn" and matching_threshold.warn_threshold:
                        threshold_limit = float(matching_threshold.warn_threshold)
                        if matching_threshold.warn_time_seconds:
                            delta = dt.timedelta(
                                seconds=matching_threshold.warn_time_seconds
                            )
                        message = warn_message
                        severity = matching_threshold.min_severity
                        # Amount of time in seconds the threshold can be breached before we actually generate an alert
                        alert_time = matching_threshold.warn_time_seconds
                        # Number of times the threshold can be breached before we actually generate an alert
                        occurrences = matching_threshold.warn_occurrences
                    else:
                        continue

                    operator = self.map_operator_to_function(
                        matching_threshold.operator
                    )
                    logging.debug(
                        f"Comparing: {current_value} {operator.__name__} {threshold_limit}"
                    )
                    is_advanced_threshold = (
                        False if not occurrences and not alert_time else True
                    )
                    if threshold_limit and operator(current_value, threshold_limit):
                        # We've breached the threshold
                        logging.debug(f"Over {threshold} threshold")
                        period = humanize.precisedelta(delta, minimum_unit="minutes")

                        message = message.format(
                            THRESHOLD=threshold_limit,
                            ALERT_TYPE=alert_type,
                            PERIOD=f"{period}",
                        )

                        # Only allow one output per threshold
                        suppress_alert = False
                        if not has_output:
                            #  Now check for any occurrence or time based conditions before outputting
                            first_occurrence = True
                            if (
                                matching_threshold.metadata
                                and "alert_cache" in matching_threshold.metadata
                            ):
                                # Loop through each instance of a previous alert to check if the threshold_no matches

                                for alert_instance in matching_threshold.metadata[
                                    "alert_cache"
                                ]:
                                    if (
                                        alert_instance["threshold_no"] == threshold_id
                                        and alert_instance["threshold_type"]
                                        == threshold
                                    ):
                                        first_occurrence = False
                                        # Determine whether to alert or not based on whether we're checking occurrences or time since first breach
                                        if occurrences:
                                            if (
                                                alert_instance["occurrences"] + 1
                                                <= occurrences
                                            ):
                                                suppress_alert = True
                                            logging.debug(
                                                f"Threshold has been breached {alert_instance['occurrences'] + 1} times - Allowed {occurrences} before alerting. {'Suppressing alert.' if suppress_alert else ''}"
                                            )
                                        if alert_time:
                                            time_since_breach_started = (
                                                time.time()
                                                - alert_instance["exceeding_start"]
                                            )
                                            if time_since_breach_started < alert_time:
                                                suppress_alert = True
                                            logging.debug(
                                                f"Threshold has been breached for {humanize.precisedelta(dt.timedelta(seconds=time_since_breach_started), minimum_unit='minutes')} - Allowed {period} before alerting. {'Suppressing alert.' if suppress_alert else ''}"
                                            )
                                        break
                            else:
                                logging.debug("No alert cache")
                            if first_occurrence:
                                # We've not breached before, so check to see if we are breaching now or not
                                if occurrences and occurrences > 1:
                                    logging.debug(
                                        f"Threshold has been breached for the first time - Allowed {occurrences} before alerting. Suppressing alert."
                                    )
                                    suppress_alert = True
                                if alert_time:
                                    logging.debug(
                                        f"Threshold has been breached for the first time - Allowed {period} before alerting. Suppressing alert."
                                    )
                                    suppress_alert = True

                            if not suppress_alert:
                                result_output = {
                                    "message": message,
                                    "alert_key": (id or threshold_id),
                                    "severity": severity,
                                    "team": matching_threshold.team,
                                }
                                logging.debug(f"Adding output line: {result_output}")
                                result.result_messages.append(result_output)

                                # self.output(
                                #     [message],
                                #     alert_key=(id or threshold_id),
                                #     severity=severity,
                                #     team=matching_threshold.team,
                                # )
                                has_output = True

                        if is_advanced_threshold:
                            # Now we've checked the warn and crit thresholds
                            # Write the status to the cache file
                            # Append/Update/Create threshold.metadata["alert_cache"]
                            # If there's no existing cache entry, create one
                            alert_instance = {}
                            if "alert_cache" not in matching_threshold.metadata:
                                alert_instance = {
                                    "threshold_type": threshold,
                                    "threshold_no": threshold_id,
                                    "exceeding_start": time.time(),
                                    "occurrences": 1,
                                }
                                matching_threshold.metadata["alert_cache"] = [
                                    alert_instance
                                ]
                            else:
                                # Find the existing cache entry and update it
                                # or create a new one if there's nothing for this threshold type
                                found_cache_entry = False
                                for alert_instance_1 in matching_threshold.metadata[
                                    "alert_cache"
                                ]:
                                    if (
                                        alert_instance_1["threshold_no"] == threshold_id
                                        and alert_instance_1["threshold_type"]
                                        == threshold
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
                                    matching_threshold.metadata["alert_cache"].append(
                                        alert_instance
                                    )

                            os.makedirs(os.path.dirname(state_file), exist_ok=True)
                            json.dump(
                                matching_threshold.metadata["alert_cache"],
                                open(state_file, "w"),
                            )

                        if not suppress_alert:
                            if severity == "Critical":
                                rc = 2
                            elif rc < 2:
                                rc = 1

                    # If the threshold isn't breached, we need to make sure it's not in the cache
                    elif is_advanced_threshold:
                        # Loop through the alert_cache to see if this alert instance exists
                        # If it does, remove it
                        cache_needs_update = False
                        if "alert_cache" in matching_threshold.metadata:
                            for alert_instance_2 in matching_threshold.metadata[
                                "alert_cache"
                            ]:
                                if (
                                    alert_instance_2["threshold_no"] == threshold_id
                                    and alert_instance_2["threshold_type"] == threshold
                                ):
                                    matching_threshold.metadata["alert_cache"].remove(
                                        alert_instance_2
                                    )
                                    logging.debug("Removed alert instance from cache")
                                    cache_needs_update = True
                                    break
                        # If we made a change, then we need to write the JSON file again
                        if cache_needs_update:
                            json.dump(
                                matching_threshold.metadata["alert_cache"],
                                open(state_file, "w"),
                            )

            if not has_output:
                logging.debug("Threshold is OK")
                result_output = {
                    "message": ok_message,
                    "alert_key": (id or threshold_id),
                    "team": matching_threshold.team,
                }
                logging.debug(f"Adding output line: {result_output}")
                result.result_messages.append(result_output)

                # self.output([ok_message], alert_key=(id or threshold_id), team=matching_threshold.team)

            if rc > result.rc:
                result.rc = rc

            threshold_id += 1

        return result

    def process_output_and_rc(
        self, threshold_result, result_message_good, result_message_alert
    ):
        rc = 0
        result_message_final = result_message_good
        if threshold_result:
            for message in threshold_result.result_messages:
                self.output(
                    [message["message"]],
                    alert_key=message["alert_key"],
                    team=message["team"],
                    severity=(message["severity"] if "severity" in message else None),
                )

            if threshold_result.rc != 0 and rc < threshold_result.rc:
                rc = threshold_result.rc
                result_message_final = result_message_alert

        return result_message_final, rc

    def map_operator_to_function(self, operator_string):
        symbol_name_map = {
            ">=": operator.ge,
            "<=": operator.le,
            ">": operator.gt,
            "<": operator.lt,
            "==": operator.eq,
            "!=": operator.ne,
        }
        return symbol_name_map[operator_string]

    def map_time_period_to_seconds(self, time_period):
        groups = self.TIME_PERIOD_REGEX.match(time_period).groups()
        return int(groups[0]) * 60 * 60 if groups[1] == "h" else int(groups[0]) * 60
