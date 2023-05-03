#!/usr/bin/env python
# -*- coding: utf-8 -*-
import re
from dataclasses import dataclass, field


@dataclass
class Threshold(object):
    id: str = None
    warn_threshold: str = None
    crit_threshold: str = None
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

    # TODO - Add X occurrences in Y mins alerting
    # TODO - Add > X for Y mins alerting

    def next_severity(self):
        if re.match(r"^Minor$", self.min_severity, re.IGNORECASE):
            return "Major"
        elif re.match(r"^(Major|Crit(ical)*)$", self.min_severity, re.IGNORECASE):
            return "Critical"
        else:
            return "Unknown"


@dataclass
class ThresholdResult(object):
    rc: int
    result_messages: list = field(default_factory=list)
