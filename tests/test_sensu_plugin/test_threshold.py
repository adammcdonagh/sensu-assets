#!/usr/bin/env python
# -*- coding: utf-8 -*-
# pylint: disable=cyclic-import
"""Test the sensu_plugin.threshold module."""
import logging

from sensu_plugin import Threshold

logging.getLogger().setLevel(logging.DEBUG)


def test_next_severity(caplog):
    """Verify that next severity is calculated correctly."""
    caplog.set_level(logging.DEBUG)
    metadata = {}
    threshold = Threshold(metadata=metadata, warn_threshold=5, team="Test")

    # Test next_severity function with no severity specified
    assert threshold.next_severity() == "Major"

    threshold.min_severity = "Major"
    assert threshold.next_severity() == "Critical"

    threshold.min_severity = "BadSeverity"
    assert threshold.next_severity() == "Unknown"
