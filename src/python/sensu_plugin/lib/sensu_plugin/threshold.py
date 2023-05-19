#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Helper module to define Sensu thresholds and threshold results."""
import re
from dataclasses import dataclass, field


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
    def __post_init__(self):
        """Check that the operator is valid."""
        if self.operator not in [">=", "<=", ">", "<"]:
            raise ValueError("Invalid operator, must be >=, <= , > or <")

    def next_severity(self):
        """Return the next severity for this threshold."""
        if re.match(r"^Minor$", self.min_severity, re.IGNORECASE):
            return "Major"
        if re.match(r"^(Major|Crit(ical)*)$", self.min_severity, re.IGNORECASE):
            return "Critical"

        return "Unknown"


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
