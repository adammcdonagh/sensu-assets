#!/usr/bin/env python
# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,unused-argument
"""Tests for the SensuPluginCheck class."""
import datetime
import logging
import os

import pytest
from freezegun import freeze_time
from sensu_plugin import SensuPluginCheck, Threshold
from sensu_plugin.logging import init_logging

logging.getLogger().setLevel(logging.DEBUG)


init_logging(__name__)


@pytest.fixture(scope="function")
def cache_dir(tmpdir):
    """Set the cache dir to a temporary directory."""
    os.environ["SENSU_CACHE_DIR"] = tmpdir.strpath


def test_basic_warn_threshold(caplog, cache_dir):
    """Test basic warn threshold outputs."""
    test_check = SensuPluginCheck()
    test_check.test_mode = True
    caplog.set_level(logging.DEBUG)
    kwargs = {}
    metadata = {}
    kwargs["metadata"] = metadata
    kwargs["warn_threshold"] = 5
    kwargs["team"] = "Test"
    threshold = Threshold(**kwargs)
    test_check.thresholds = [threshold]

    # Set up a standard threshold with an ID
    test_values = [
        {
            "current_value": 1,
            "expected_rc": 0,
            "expected_severity": None,
            "expected_message": "current_value is 1",
            "alert_key": "ID1",
        },
        {
            "current_value": 5,
            "expected_rc": 1,
            "expected_severity": "Minor",
            "expected_message": "Current value is >= 5.0",
            "alert_key": "ID1",
        },
        {
            "current_value": 6,
            "expected_rc": 1,
            "expected_severity": "Minor",
            "expected_message": "Current value is >= 5.0",
            "alert_key": "ID1",
        },
    ]

    run_process_value_check(test_values, test_check, ">=")

    # Set up a standard threshold with no ID
    test_values = [
        {
            "current_value": 2,
            "expected_rc": 0,
            "expected_severity": None,
            "expected_message": "current_value is 2",
        },
        {
            "current_value": 5,
            "expected_rc": 1,
            "expected_severity": "Minor",
            "expected_message": "Current value is >= 5.0",
        },
        {
            "current_value": 7,
            "expected_rc": 1,
            "expected_severity": "Minor",
            "expected_message": "Current value is >= 5.0",
        },
    ]

    run_process_value_check(test_values, test_check, ">=")


def test_basic_warn_with_crit_threshold(caplog, cache_dir):
    """Test basic warn with a critical threshold outputs."""
    test_check = SensuPluginCheck()
    test_check.test_mode = True
    caplog.set_level(logging.DEBUG)
    kwargs = {}
    metadata = {}
    kwargs["metadata"] = metadata
    kwargs["warn_threshold"] = 5
    kwargs["crit_threshold"] = 10
    kwargs["team"] = "Test"
    threshold = Threshold(**kwargs)
    test_check.thresholds = [threshold]

    # Set up a standard threshold with an ID
    test_values = [
        {
            "current_value": 1,
            "expected_rc": 0,
            "expected_severity": None,
            "expected_message": "current_value is 1",
            "alert_key": "ID1",
        },
        {
            "current_value": 5,
            "expected_rc": 1,
            "expected_severity": "Minor",
            "expected_message": "Current value is >= 5.0",
            "alert_key": "ID2",
        },
        {
            "current_value": 10,
            "expected_rc": 1,
            "expected_severity": "Major",
            "expected_message": "Current value is >= 10.0",
            "alert_key": "ID3",
        },
    ]

    run_process_value_check(test_values, test_check, ">=", check_alert_key=True)

    # Set up a standard threshold with no ID
    test_values = [
        {
            "current_value": 2,
            "expected_rc": 0,
            "expected_severity": None,
            "expected_message": "current_value is 2",
        },
        {
            "current_value": 5,
            "expected_rc": 1,
            "expected_severity": "Minor",
            "expected_message": "Current value is >= 5.0",
        },
        {
            "current_value": 10,
            "expected_rc": 1,
            "expected_severity": "Major",
            "expected_message": "Current value is >= 10.0",
        },
    ]

    run_process_value_check(test_values, test_check, ">=")

    # Redefine the threshold with a higher min severity to check rc 2 return codes
    kwargs["metadata"] = metadata
    kwargs["warn_threshold"] = 5
    kwargs["crit_threshold"] = 10
    kwargs["min_severity"] = "Major"
    kwargs["team"] = "Test"
    threshold = Threshold(**kwargs)
    test_check.thresholds = [threshold]

    test_values = [
        {
            "current_value": 2,
            "expected_rc": 0,
            "expected_severity": None,
            "expected_message": "current_value is 2",
        },
        {
            "current_value": 5,
            "expected_rc": 1,
            "expected_severity": "Major",
            "expected_message": "Current value is >= 5.0",
        },
        {
            "current_value": 10,
            "expected_rc": 2,
            "expected_severity": "Critical",
            "expected_message": "Current value is >= 10.0",
        },
    ]

    run_process_value_check(test_values, test_check, ">=")


def test_basic_crit_threshold(caplog, cache_dir):
    """Test basic crit threshold with min severity of Major."""
    test_check = SensuPluginCheck()
    test_check.test_mode = True
    caplog.set_level(logging.DEBUG)
    kwargs = {}
    metadata = {}
    kwargs["metadata"] = metadata
    kwargs["min_severity"] = "Major"
    kwargs["warn_threshold"] = 5
    kwargs["crit_threshold"] = 10
    kwargs["team"] = "Test"
    threshold = Threshold(**kwargs)
    test_check.thresholds = [threshold]

    test_values = [
        {
            "current_value": 10,
            "expected_rc": 2,
            "expected_severity": "Critical",
            "expected_message": "Current value is >= 10.0",
        },
    ]

    run_process_value_check(test_values, test_check, ">=")


def test_advanced_warn_threshold_occurrences(caplog, cache_dir):
    """Test advanced warn threshold with number of occurrences."""
    test_check = SensuPluginCheck()
    test_check.test_mode = True
    caplog.set_level(logging.DEBUG)
    kwargs = {}
    metadata = {}
    kwargs["metadata"] = metadata
    kwargs["min_severity"] = "Major"
    kwargs["warn_threshold"] = 5
    kwargs["warn_occurrences"] = 2
    kwargs["team"] = "Test"
    threshold = Threshold(**kwargs)
    test_check.thresholds = [threshold]

    # Run the check once, check that it doesnt error
    test_values = [
        {
            "current_value": 10,
            "expected_rc": 0,
            "expected_severity": None,
            "expected_message": "current_value is 10",
        },
    ]
    logging.info("Testing occurrence 1")
    run_process_value_check(test_values, test_check, ">=")

    # Run the checks a second time, also check it doesnt error
    test_values = [
        {
            "current_value": 10,
            "expected_rc": 0,
            "expected_severity": None,
            "expected_message": "current_value is 10",
        },
    ]
    logging.info("Testing occurrence 2")
    run_process_value_check(test_values, test_check, ">=")

    # Run the check a 3rd time and check that it does error
    test_values = [
        {
            "current_value": 10,
            "expected_rc": 1,
            "expected_severity": "Major",
            "expected_message": "Current value is >= 5.0",
        },
    ]
    logging.info("Testing occurrence 3")
    run_process_value_check(test_values, test_check, ">=")


def test_advanced_warn_and_crit_threshold_occurrences(caplog, cache_dir):
    """Test advanced warn and critical threshold with number of occurrences."""
    test_check = SensuPluginCheck()
    test_check.test_mode = True
    caplog.set_level(logging.DEBUG)
    kwargs = {}
    metadata = {}
    kwargs["metadata"] = metadata
    kwargs["min_severity"] = "Major"
    kwargs["warn_threshold"] = 5
    kwargs["crit_threshold"] = 11
    kwargs["warn_occurrences"] = 2
    kwargs["crit_occurrences"] = 3
    kwargs["team"] = "Test"
    threshold = Threshold(**kwargs)
    test_check.thresholds = [threshold]

    # Run the check once, check that it doesnt error

    test_values = [
        {
            "current_value": 10,
            "expected_rc": 0,
            "expected_severity": None,
            "expected_message": "current_value is 10",
        },
    ]
    logging.info("Testing occurrence 1")
    run_process_value_check(test_values, test_check, ">=")

    # Run the checks a second time, also check it doesnt error
    test_values = [
        {
            "current_value": 10,
            "expected_rc": 0,
            "expected_severity": None,
            "expected_message": "current_value is 10",
        },
    ]
    logging.info("Testing occurrence 2")
    run_process_value_check(test_values, test_check, ">=")

    # Run the check a 3rd time and check that it does error for the major threshold
    test_values = [
        {
            "current_value": 10,
            "expected_rc": 1,
            "expected_severity": "Major",
            "expected_message": "Current value is >= 5.0",
        },
    ]
    logging.info("Testing occurrence 3")
    run_process_value_check(test_values, test_check, ">=")

    # Now we alter the current value to 11, so we are breaching the critical threshold
    # We should continue to get a major alert, until the critical threshold is breached 3 times

    # Run the 4th time and check we still get a Major alert
    test_values = [
        {
            "current_value": 11,
            "expected_rc": 1,
            "expected_severity": "Major",
            "expected_message": "Current value is >= 5.0",
        },
    ]
    logging.info("Testing occurrence 4")
    run_process_value_check(test_values, test_check, ">=")

    # Run the 5th time and check still get Major
    test_values = [
        {
            "current_value": 11,
            "expected_rc": 1,
            "expected_severity": "Major",
            "expected_message": "Current value is >= 5.0",
        },
    ]
    logging.info("Testing occurrence 5")
    run_process_value_check(test_values, test_check, ">=")

    # Now the critical threshold has had 3 occurrences, so its the last time it will be just Major

    # Run the 6th time and check we get a Major
    test_values = [
        {
            "current_value": 11,
            "expected_rc": 1,
            "expected_severity": "Major",
            "expected_message": "Current value is >= 5.0",
        },
    ]
    logging.info("Testing occurrence 6")
    run_process_value_check(test_values, test_check, ">=")

    # Final run, we should get just a critical alert, with the updated output message
    test_values = [
        {
            "current_value": 11,
            "expected_rc": 2,
            "expected_severity": "Critical",
            "expected_message": "Current value is >= 11.0",
        },
    ]
    logging.info("Testing occurrence 7")
    run_process_value_check(test_values, test_check, ">=")


def test_advanced_warn_threshold_time(caplog, cache_dir):
    """Test advanced warn threshold with time."""
    test_check = SensuPluginCheck()
    test_check.test_mode = True
    caplog.set_level(logging.DEBUG)
    kwargs = {}
    metadata = {}
    kwargs["metadata"] = metadata
    kwargs["min_severity"] = "Major"
    kwargs["warn_threshold"] = 5
    kwargs["warn_time_seconds"] = 5
    kwargs["team"] = "Test"
    threshold = Threshold(**kwargs)
    test_check.thresholds = [threshold]

    # Run the check once, check that it doesnt error
    test_values = [
        {
            "current_value": 10,
            "expected_rc": 0,
            "expected_severity": None,
            "expected_message": "current_value is 10",
        },
    ]
    with freeze_time(datetime.datetime.now()) as frozen_datetime:
        logging.info("Testing occurrence 1")
        run_process_value_check(test_values, test_check, ">=")

        # Advance time by 5 seconds
        frozen_datetime.tick(5)

        # Run the checks a second time, also check it errors
        test_values = [
            {
                "current_value": 10,
                "expected_rc": 1,
                "expected_severity": "Major",
                "expected_message": "Current value is >= 5.0",
            },
        ]
        logging.info("Testing occurrence 2")
        run_process_value_check(test_values, test_check, ">=")


def test_advanced_warn_and_crit_threshold_time(caplog, cache_dir):
    """Test advanced warn and crit threshold with time."""
    test_check = SensuPluginCheck()
    test_check.test_mode = True
    caplog.set_level(logging.DEBUG)
    kwargs = {}
    metadata = {}
    kwargs["metadata"] = metadata
    kwargs["min_severity"] = "Major"
    kwargs["warn_threshold"] = 5
    kwargs["crit_threshold"] = 11
    kwargs["warn_time_seconds"] = 5
    kwargs["crit_time_seconds"] = 10
    kwargs["team"] = "Test"
    threshold = Threshold(**kwargs)
    test_check.thresholds = [threshold]

    # Run the check once, check that it doesnt error
    test_values = [
        {
            "current_value": 11,
            "expected_rc": 0,
            "expected_severity": None,
            "expected_message": "current_value is 11",
        },
    ]
    with freeze_time(datetime.datetime.now()) as frozen_datetime:
        logging.info("Testing occurrence 1")
        run_process_value_check(test_values, test_check, ">=")

        # Skip 5 seconds
        frozen_datetime.tick(5)

        # Run the checks a second time, we should get a Major alert
        test_values = [
            {
                "current_value": 11,
                "expected_rc": 1,
                "expected_severity": "Major",
                "expected_message": "Current value is >= 5.0",
            },
        ]
        logging.info("Testing occurrence 2")
        run_process_value_check(test_values, test_check, ">=")

        # We should continue to get a major alert, until the critical threshold has been breached for 10 seconds
        frozen_datetime.tick(2)

        # Run the 3rd time and check we still get a Major alert
        test_values = [
            {
                "current_value": 11,
                "expected_rc": 1,
                "expected_severity": "Major",
                "expected_message": "Current value is >= 5.0",
            },
        ]
        logging.info("Testing occurrence 3")
        run_process_value_check(test_values, test_check, ">=")

        # We should continue to get a major alert, until the critical threshold has been breached for 10 seconds
        frozen_datetime.tick(5)

        # Run the 4th time and check we now get a Critical alert
        test_values = [
            {
                "current_value": 11,
                "expected_rc": 2,
                "expected_severity": "Critical",
                "expected_message": "Current value is >= 11.0",
            },
        ]
        logging.info("Testing occurrence 4")
        run_process_value_check(test_values, test_check, ">=")


def test_advanced_warn_threshold_x_in_y(caplog, cache_dir):
    """Test advanced warn threshold with number of occurrences over a time period."""
    test_check = SensuPluginCheck()
    test_check.test_mode = True
    caplog.set_level(logging.DEBUG)
    kwargs = {}
    metadata = {}
    kwargs["metadata"] = metadata
    kwargs["min_severity"] = "Major"
    kwargs["warn_threshold"] = 5
    kwargs["warn_occurrences"] = 5
    kwargs["warn_time_seconds"] = 6
    kwargs["team"] = "Test"
    threshold = Threshold(**kwargs)
    test_check.thresholds = [threshold]

    initial_datetime = datetime.datetime(
        year=2000, month=1, day=1, hour=0, minute=0, second=0
    )

    with freeze_time(initial_datetime) as frozen_datetime:
        # Run the check once, check that it doesnt error
        test_values = [
            {
                "current_value": 10,
                "expected_rc": 0,
                "expected_severity": None,
                "expected_message": "current_value is 10",
            },
        ]
        logging.info("Testing occurrence 1")
        run_process_value_check(test_values, test_check, ">=")
        # Advance the clock by 1 second
        frozen_datetime.tick()

        # Trigger it again another 4 times, check that it doesnt error
        test_values = [
            {
                "current_value": 10,
                "expected_rc": 0,
                "expected_severity": None,
                "expected_message": "current_value is 10",
            },
        ]
        for occurrence in range(2, 6):
            logging.info(f"Testing occurrence {occurrence}")
            run_process_value_check(test_values, test_check, ">=")
            # Advance the clock by 1 second
            frozen_datetime.tick()

        # Advance the block by a further 6 seconds
        frozen_datetime.tick(6)
        # Now run the check again, check that it does error
        test_values = [
            {
                "current_value": 10,
                "expected_rc": 1,
                "expected_severity": "Major",
                "expected_message": "Current value is >= 5.0",
            },
        ]
        logging.info("Testing occurrence 6")
        run_process_value_check(test_values, test_check, ">=")


@freeze_time("2022-05-04 15:00:00")
def test_basic_warn_threshold_with_exclude_period(caplog, cache_dir):
    """Test basic warn threshold with exclude period."""
    logging.info(f"Current time is {datetime.datetime.now()}")

    test_check = SensuPluginCheck()
    test_check.test_mode = True
    caplog.set_level(logging.DEBUG)
    kwargs = {}
    metadata = {}
    kwargs["metadata"] = metadata
    kwargs["min_severity"] = "Major"
    kwargs["warn_threshold"] = 5
    kwargs["exclude_times"] = [
        {"days_of_week": ["Wednesday"], "start_time": "10:00", "end_time": "16:00"}
    ]

    kwargs["team"] = "Test"
    threshold = Threshold(**kwargs)
    test_check.thresholds = [threshold]

    # Run the test and make sure we don't get any alerts
    test_values = [
        {
            "current_value": 11,
            "expected_rc": 0,
            "expected_severity": None,
            "expected_message": "current_value is 11",
        },
    ]
    logging.info("Running first test, inside exclusion period")
    run_process_value_check(test_values, test_check, ">=")

    # Alter the threshold so that we're outside the exclusion period
    kwargs["exclude_times"] = [
        {"days_of_week": ["Wednesday"], "start_time": "10:00", "end_time": "11:00"}
    ]
    threshold = Threshold(**kwargs)
    test_check.thresholds = [threshold]

    # Run the test and make sure we get a warning
    test_values = [
        {
            "current_value": 11,
            "expected_rc": 1,
            "expected_severity": "Major",
            "expected_message": "Current value is >= 5.0",
        },
    ]

    logging.info("Running second test, outside of exclusion period")
    run_process_value_check(test_values, test_check, ">=")


def run_process_value_check(test_values, test_check, operator, check_alert_key=False):
    """Run the process_value check for the given test values."""
    for test_value in test_values:
        current_value = test_value["current_value"]
        alert_id = test_value["alert_key"] if "alert_key" in test_value else None
        threshold_result = test_check.process_value(
            alert_id,
            current_value,
            ok_message=f"current_value is {current_value}",
            alert_message=f"Current value is {operator} ::THRESHOLD::",
        )

        assert threshold_result.rc == test_value["expected_rc"]
        assert (
            threshold_result.result_messages[0]["message"]
            == test_value["expected_message"]
        )
        if test_value["expected_severity"]:
            assert (
                threshold_result.result_messages[0]["severity"]
                == test_value["expected_severity"]
            )
        if check_alert_key:
            assert (
                threshold_result.result_messages[0]["alert_key"]
                == test_value["alert_key"]
            )
