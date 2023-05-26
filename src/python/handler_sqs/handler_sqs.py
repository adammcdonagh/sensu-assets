#!/usr/bin/env python
"""Sensu Handler for pushing events into an SQS queue for processing."""

import argparse
import json
import logging
import os
import re
import sys
import time
from copy import deepcopy
from datetime import datetime
from typing import Any

import boto3
from sensu_plugin import EnvDefault, SensuAsset, write_log_file

DEFAULT_TTL = 120 * 60  # 2hrs
SEVERITY_MAP = {"Clear": 9, "Minor": 3, "Major": 4, "Critical": 5}

# Regexes for handling known line formats from Sensu check results
ALERT_LINE_PATTERN = re.compile(
    r"^(?P<monitor_name>[^\s]+) (?:WARN|CRITICAL|CRIT|OK): (?P<summary>.*?) \|"
    r" (?:KEY:(?P<key>.*?)) (?:SEV:(?P<severity>Major|Minor|Crit(?:ical)*|Clear))*(?:"
    r" (?:TEAM:(.*?)))*(?: (?:SOURCE:(.*?)))*$"
)
SUCCESS_LINE_PATTERN = re.compile(r"^(?P<monitor_name>[^\s]+) OK: (?P<summary>.*?)$")

NO_KEEPALIVE_LINE_PATTERN = re.compile(r"^No keepalive sent from .*? for (\d+) seconds")
KEEPALIVE_OK_LINE_PATTERN = re.compile(r"Keepalive last sent from")
TIMEOUT_LINE_PATTERN = re.compile(
    r"^Execution timed out|Unable to TERM.KILL the process"
)
GRAPHITE_LINE_PATTERN = re.compile(r"^([^\s]+) ([^\s]+) \d+$")


class HandlerSQS(SensuAsset):  # pylint: disable=too-few-public-methods
    """Handles incoming events from Sensu and passes to SQS.

    This class handles incoming events from Sensu, processes them based on severity
    and previous state (stored in DynamoDB) and forwards them to an SQS queue.
    """

    def __init__(self) -> None:
        """Initialise the class."""
        # Call the parent init
        super().__init__()
        self.args = self._parse_cli_args()
        self.run()

    def _parse_cli_args(self) -> argparse.Namespace:
        parser = argparse.ArgumentParser(
            formatter_class=argparse.ArgumentDefaultsHelpFormatter
        )
        parser.add_argument(
            "-v",
            "--verbose",
            required=False,
            help="turn on verbose output",
            action="store_true",
        )

        parser.add_argument(
            "-vv",
            "--extra_verbose",
            help="Enable debug logging and boto debug",
            action="store_true",
        )

        parser.add_argument(
            "-u",
            "--aws_endpoint_url",
            required=True,
            help=(
                "AWS endpoint URL (can also be specified via AWS_ENDPOINT_URL"
                " environment variable)"
            ),
            action=EnvDefault,
            envvar="AWS_ENDPOINT_URL",
        )

        parser.add_argument(
            "-t",
            "--dynamodb_table",
            required=True,
            help=(
                "DynamoDB table to store state (can also be specified via"
                " DYNAMODB_TABLE environment variable)"
            ),
            action=EnvDefault,
            envvar="DYNAMODB_TABLE",
        )

        parser.add_argument(
            "-q",
            "--sqs_queue",
            required=True,
            help=(
                "SQS queue to send events to (can also be specified via SQS_QUEUE"
                " environment variable)"
            ),
            action=EnvDefault,
            envvar="SQS_QUEUE",
        )

        parser.add_argument(
            "--offline_agent_responsible_team",
            required=False,
            help="Default team name to associate offline agent alerts with",
            action=EnvDefault,
            envvar="OFFLINE_AGENT_RESPONSIBLE_TEAM",
        )

        return parser.parse_args()

    def run(self) -> int:
        """Run the handler."""
        # Setup custom logging for boto3
        self._setup_logging()

        # Strip out any proxy settings from the environment
        os.environ["HTTP_PROXY"] = ""
        os.environ["HTTPS_PROXY"] = ""
        os.environ["http_proxy"] = ""
        os.environ["https_proxy"] = ""

        # Parse event data from STDIN
        stdin_event = "".join(sys.stdin.readlines())

        # Write STDIN to /tmp
        with open(
            "/tmp/event.json", "w", encoding="utf-8"  # nosec B108
        ) as file_handle:
            file_handle.write(stdin_event)

        # Parse the event into JSON format
        json_object = json.loads(stdin_event)

        # Get objects for interacting with DynamoDB and SQS
        self.ddb_table = (
            boto3.Session()
            .resource("dynamodb", endpoint_url=self.args.aws_endpoint_url)
            .Table(self.args.dynamodb_table)
        )
        self.sqs_queue = (
            boto3.Session()
            .resource("sqs", endpoint_url=self.args.aws_endpoint_url)
            .get_queue_by_name(QueueName=self.args.sqs_queue)
        )

        # Pull out the raw check output
        check_output = json_object["check"]["output"].split("\n")

        # Loop through the check output and pull out all the lines that conform to the alert pattern
        for check_line in check_output:
            # Parse the line and extract all the important attributes
            # Skip the line if there's no attributes found
            if not (
                alert_attributes := self._parse_alert_line(check_line, json_object)
            ):
                continue

            self.logger.debug(f"Alert attributes: {alert_attributes}")

            # Alert key for this line
            alert_key = f"{alert_attributes['monitor_name']}_{alert_attributes['key']}_{alert_attributes['source']}"

            # BEFORE sending anything, we need to determine exactly what to send based
            # on the status of the message

            # Check in DynamoDB for a matching key
            skip_alert = False
            self.logger.debug(f"Searching DynamoDB for {alert_key}")
            table_item = self.ddb_table.get_item(Key={"alert_key": alert_key})

            skip_alert = self._handle_existing_alert(
                table_item, alert_attributes, alert_key
            )

            if not skip_alert:
                # Send the alert to the SQS queue
                send_response = self._send_to_sqs(
                    self.sqs_queue, alert_key, alert_attributes
                )
                self.logger.debug(send_response)

            self.logger.debug("")
        return 0

    def _put_event_in_db(
        self, ddb_table: Any, alert_key: str, alert_attributes: dict
    ) -> Any:
        """Put the event in DynamoDB.

        :param ddb_table: DynamoDB table object
        :param alert_key: Alert key
        :param alert_attributes: Alert attributes
        :return: Result of the put_item call
        """
        result = ddb_table.put_item(
            Item={
                "alert_key": alert_key,
                "summary": alert_attributes["summary"],
                "expiration_time": int(time.time()) + alert_attributes["ttl"],
                "source": alert_attributes["source"],
                "severity": alert_attributes["severity"],
            },
        )
        self.logger.debug(f"Put in DynamoDB: {result}")
        return result

    def _send_to_sqs(
        self, sqs_queue: Any, alert_key: str, alert_attributes: dict
    ) -> Any:
        """Send the event to SQS.

        :param sqs_queue: SQS queue object
        :param alert_key: Alert key
        :param alert_attributes: Alert attributes
        :return: Result of the send_message call
        """
        mapped_severity = SEVERITY_MAP[alert_attributes["severity"]]
        # Construct the message
        insert_time = int(time.time())
        insert_timestamp = datetime.fromtimestamp(insert_time).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        message_body = {
            "node": alert_attributes["source"],
            "alertKey": alert_key,
            "summary": alert_attributes["summary"],
            "severity": mapped_severity,
            "team": alert_attributes["team"] if "team" in alert_attributes else None,
            "expiry": alert_attributes["expiry"]
            if "expiry" in alert_attributes
            else None,
            "environment": alert_attributes["environment"],
            "insertTime": time.time(),
            "insertTimestamp": insert_timestamp,
        }

        message_body_ = json.dumps(message_body)
        self.logger.debug(f"Sent to SQS: {message_body_}")
        return sqs_queue.send_message(
            MessageBody=message_body_, MessageGroupId=alert_attributes["monitor_name"]
        )

    def _setup_logging(self) -> None:
        """Set logging for other packages."""
        if self.args.verbose:
            logging.getLogger().setLevel(logging.DEBUG)

        if self.args.extra_verbose:
            logging.getLogger("boto3").setLevel(logging.DEBUG)
            logging.getLogger("botocore").setLevel(logging.DEBUG)
            logging.getLogger("nose").setLevel(logging.DEBUG)
            logging.getLogger("s3transfer").setLevel(logging.DEBUG)
            logging.getLogger("urllib3").setLevel(logging.DEBUG)

    def _parse_alert_line(  # pylint: disable=too-many-statements,too-many-branches
        self, check_line: str, event_object: dict
    ) -> dict | None:
        alert_attributes = {}

        # Parse the line
        alert_line_match = ALERT_LINE_PATTERN.match(check_line)
        success_line_match = SUCCESS_LINE_PATTERN.match(check_line)
        no_keepalive_line_match = NO_KEEPALIVE_LINE_PATTERN.match(check_line)
        timeout_line_match = TIMEOUT_LINE_PATTERN.match(check_line)
        graphite_line_match = GRAPHITE_LINE_PATTERN.match(check_line)
        keepalive_ok_line_match = KEEPALIVE_OK_LINE_PATTERN.match(check_line)

        # Ignore blank lines
        if check_line == "":
            return None

        if alert_line_match:
            # Standard alert line. Use the named variables in the regex to map to the
            # alert attributes
            alert_attributes = alert_line_match.groupdict()

            # Alter the key so that it doesn't contain any forward slashes
            alert_attributes["key"] = alert_attributes["key"].replace("/", "_")
        elif success_line_match:
            return None
        elif no_keepalive_line_match:
            alert_attributes["summary"] = (
                "Sensu agent offline ",
                (
                    "- No communication for"
                    f" {(float(no_keepalive_line_match.group(1))/60):.1f} mins"
                ),
            )
            alert_attributes["monitor_name"] = "keepalive"
            alert_attributes["team"] = self.args.offline_agent_responsible_team
            alert_attributes["severity"] = "Major"
            alert_attributes["key"] = "Sensu agent offline"
            alert_attributes["ttl"] = 130

        elif keepalive_ok_line_match:
            alert_attributes["summary"] = "CLEAR - Sensu agent is now online"
            alert_attributes["monitor_name"] = "keepalive"
            alert_attributes["team"] = self.args.offline_agent_responsible_team
            alert_attributes["severity"] = "Clear"
            alert_attributes["key"] = "Sensu agent offline"

        elif timeout_line_match:
            # Skip timeouts until they have happened 3 times in a row
            if event_object["check"]["occurrences"] < 3:
                logging.debug("Ignoring timeout until there have been 3 occurrences")
                return None

            alert_attributes["summary"] = (
                f"Timeout running - {event_object['check']['metadata']['name']} ",
                (
                    "- Monitor frequency is:"
                    f" {(float(event_object['check']['interval'])/60):.1f} mins."
                ),
            )
            alert_attributes["monitor_name"] = "timeout"
            alert_attributes["key"] = event_object["check"]["metadata"]["name"]
            alert_attributes["team"] = self.args.offline_agent_responsible_team
            alert_attributes["severity"] = "Minor"
            alert_attributes["ttl"] = event_object["check"]["interval"] + 15
        elif graphite_line_match:
            # Ignore anything that's graphite metrics
            return None
        else:
            # This is an unhandled format, output a generic message
            alert_attributes["summary"] = (
                "Invalid Sensu check result",
                f"- {event_object['check']['metadata']['name']} - {check_line}",
            )
            alert_attributes["team"] = self.args.offline_agent_responsible_team
            alert_attributes["severity"] = "Minor"
            alert_attributes["ttl"] = event_object["check"]["interval"] + 15

        # Set the common values for the alert attributes

        # Default using the entity name as the source
        if "source" not in alert_attributes:
            alert_attributes["source"] = event_object["entity"]["metadata"]["name"]
        if "monitor_name" not in alert_attributes:
            alert_attributes["monitor_name"] = ""

        # Get the environment value from the entity labels
        alert_attributes["environment"] = event_object["entity"]["metadata"]["labels"][
            "environment"
        ]

        if re.search(
            r"(check.*has not run recently|Metric check.*is erroring)",
            alert_attributes["summary"],
        ):
            alert_attributes["ttl"] = event_object["check"]["interval"] + 10

        # If the alert is clearing, then append this to the start of the summary
        if (
            "severity" not in alert_attributes
            or not alert_attributes["severity"]
            or alert_attributes["severity"] == "Clear"
        ):
            alert_attributes["summary"] = f"CLEAR - {alert_attributes['summary']}"
            alert_attributes["severity"] = "Clear"

        # Ensure production events are labelled with the full name
        if alert_attributes["environment"].lower() == "prod":
            alert_attributes["environment"] = "Production"

        # Handle expiry properly now
        ttl = DEFAULT_TTL
        if (
            "interval" in alert_attributes
            and int(alert_attributes["interval"]) > 0
            and "ttl" not in alert_attributes
        ):
            ttl = int(alert_attributes["interval"]) * 3
        ttl = max(ttl, 10)
        alert_attributes["ttl"] = ttl

        return alert_attributes

    def _handle_existing_alert(
        self, table_item: dict, alert_attributes: dict, alert_key: str
    ) -> bool:
        """Handles an existing alert in the DB.

        If there's an existing alert in the database with the same alert_key, then we
        need to determine what to do with it.

            If the severity is different to the previous alert, then we need to clear
            the previous alert before the new one is sent

            If the alert is a clear, the alert needs to be deleted from the database

            If it isn't clear, then we will update the existing entry so that the TTL is
            reset/extended, and severity updated to match the current state

        If there is no previous alert:

            If the alert is not a clear, then we need to insert it into the database

            Otherwise, if it's not the Sensu Heartbeat and not a MetricsStatus result,
            then we need to skip it, and it would have already been cleared (because
            it's not in the database)
                If it is the Sensu Heartbeat, then we will still send it, but we change
                the severity to Info

        Returns True if the alert should be skipped, False if it should be sent
        """
        skip_alert = False
        if "Item" in table_item:
            existing_event = table_item["Item"]
            logging.debug(
                f"Found existing entry with severity {existing_event['severity']}."
                f" Current severity is {alert_attributes['severity']}"
            )

            # If the previous severity is different, and the new severity isn't a clear,
            # send a clear for the previous severity
            if (
                existing_event["severity"] != alert_attributes["severity"]
                and alert_attributes["severity"] != "Clear"
            ):
                logging.debug(
                    f"Sending clear for original {existing_event['severity']} severity"
                )
                # Take a copy of the existing event, so we can set it to clear and
                # send it
                cloned_attributes = deepcopy(alert_attributes)
                cloned_attributes["severity"] = "Clear"
                send_response = self._send_to_sqs(
                    self.sqs_queue, alert_key, cloned_attributes
                )
                logging.debug(send_response)

            elif alert_attributes["severity"] == "Clear":
                # Delete the event from the table
                self.ddb_table.delete_item(Key={"alert_key": alert_key})

            # Now we can send the actual alert
            if alert_attributes["severity"] != "Clear":
                # Reinsert the event into the table so the TTL and severity is updated
                logging.debug("Updating existing entry")
                self._put_event_in_db(self.ddb_table, alert_key, alert_attributes)

        else:
            # If this isn't a clear, we need to
            #  insert a new value into the DB

            if alert_attributes["severity"] != "Clear":
                logging.debug("Inserting new entry")

                self._put_event_in_db(self.ddb_table, alert_key, alert_attributes)
            else:
                if (
                    alert_attributes["monitor_name"] != "SensuHB"
                    and alert_attributes["monitor_name"] != "MetricsStatus:"
                ):
                    logging.debug("Skipping sending trap for already cleared alert")
                    skip_alert = True
                elif alert_attributes["monitor_name"] == "SensuHB":
                    # Severity always needs to be at Info level so it doesn't clear
                    alert_attributes["severity"] = "Info"

        return skip_alert


if __name__ == "__main__":
    start_time = round(time.time() * 1000)
    HandlerSQS()
    end_time = round(time.time() * 1000)
    write_log_file(f"Runtime: {end_time - start_time} ms")
