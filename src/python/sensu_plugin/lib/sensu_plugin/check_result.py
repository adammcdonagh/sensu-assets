#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Contains the CheckResultMetadata class."""
from dataclasses import dataclass


@dataclass
class CheckResultMetadata:
    """Class to hold the metadata for the check result.

    Attributes:
        ok_message (str): Message to be output if the check is OK
        warn_message (str): Message to be output if the check is WARN
        crit_message (str): Message to be output if the check is CRIT
        check_name (str): Name of the check
        alert_id (str): ID of the alert
        alert_type (str): Type of the alert
        state_file_dir (str): Directory containing state files
    """

    ok_message: str
    warn_message: str
    crit_message: str
    check_name: str
    alert_id: str
    alert_type: str
    state_file_dir: str
