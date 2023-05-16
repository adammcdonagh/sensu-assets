#!/usr/bin/env python
"""
Sensu Handler for pushing events into
an SQS queue for processing
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from copy import deepcopy

import boto3
from sensu_plugin.logging import init_logging, write_log_file

# This script handles incoming events from Sensu, processes them based on severity and previous state (stored in DynamoDB)
# and forwards them to an SQS queue
DEFAULT_TTL = 120 * 60  # 2hrs
SEVERITY_MAP = {"Clear": 9, "Minor": 3, "Major": 4, "Critical": 5}


def put_event_in_db(ddb_table, alert_key: str, alert_attributes: dict) -> dict:
    """
    Put the event in DynamoDB

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
    logging.debug(f"Put in DynamoDB: {result}")
    return result


def send_to_sqs(sqs_queue, alert_key: str, alert_attributes: dict) -> dict:
    """
    Send the event to SQS

    :param sqs_queue: SQS queue object
    :param alert_key: Alert key
    :param alert_attributes: Alert attributes
    :return: Result of the send_message call
    """
    mapped_severity = SEVERITY_MAP[alert_attributes["severity"]]
    # Construct the message
    message_body = {
        "node": alert_attributes["source"],
        "alertKey": alert_key,
        "summary": alert_attributes["summary"],
        "severity": mapped_severity,
        "team": alert_attributes["team"] if "team" in alert_attributes else None,
        "expiry": alert_attributes["expiry"] if "expiry" in alert_attributes else None,
        "environment": alert_attributes["environment"],
        "insertTime": time.time(),
    }

    message_body = json.dumps(message_body)
    logging.debug(f"Sent to SQS: {message_body}")
    return sqs_queue.send_message(
        MessageBody=message_body, MessageGroupId=alert_attributes["monitor_name"]
    )


def main() -> int:
    """
    Main function

    :return: 0 on success, 1 on failure
    """

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
        "-t",
        "--dynamodb_table",
        required=True,
        help="DynamoDB table to store state",
    )

    parser.add_argument(
        "-q",
        "--sqs_queue",
        required=True,
        help="SQS queue to send events to",
    )

    # Strip out any proxy settings from the environment
    os.environ["HTTP_PROXY"] = ""
    os.environ["HTTPS_PROXY"] = ""
    os.environ["http_proxy"] = ""
    os.environ["https_proxy"] = ""

    session = boto3.Session()

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.extra_verbose:
        logging.getLogger("boto3").setLevel(logging.DEBUG)
        logging.getLogger("botocore").setLevel(logging.DEBUG)
        logging.getLogger("nose").setLevel(logging.DEBUG)
        logging.getLogger("s3transfer").setLevel(logging.DEBUG)
        logging.getLogger("urllib3").setLevel(logging.DEBUG)

    # Parse event data from STDIN
    stdin_event = "".join(sys.stdin.readlines())

    # Write STDIN to /tmp
    with open("/tmp/event.json", "w", encoding="utf-8") as file_handle:
        file_handle.write(stdin_event)

    # Parse the event into JSON format
    json_object = json.loads(stdin_event)

    aws_endpoint_url = os.environ.get("AWS_ENDPOINT_URL", None)

    # Setup a boto3 client
    ddb = session.resource("dynamodb", endpoint_url=aws_endpoint_url)
    ddb_table = ddb.Table(args.dynamodb_table)

    sqs = session.resource("sqs", endpoint_url=aws_endpoint_url)
    sqs_queue = sqs.get_queue_by_name(QueueName=args.sqs_queue)

    # Pull our the raw check output
    check_output = json_object["check"]["output"].split("\n")
    # if ( $line =~ m/^([^\s]+) (WARN|CRITICAL|CRIT|OK): .*? \| ([^,]+),([^,]+),([^,]*),([^,]*),([^,]+),([^,]+)$/ ) {
    # LinuxFilesystemMetrics CRITICAL: Filesystem usage for /etc/hostname is OK (79.7% used) | SEV:Major
    alert_line_pattern = re.compile(
        r"^(?P<monitor_name>[^\s]+) (?:WARN|CRITICAL|CRIT|OK): (?P<summary>.*?) \| (?:KEY:(?P<key>.*?)) (?:SEV:(?P<severity>Major|Minor|Crit(?:ical)*|Clear))*(?: (?:TEAM:(.*?)))*(?: (?:SOURCE:(.*?)))*$"
    )
    success_line_pattern = re.compile(
        r"^(?P<monitor_name>[^\s]+) OK: (?P<summary>.*?)$"
    )

    no_keepalive_line_pattern = re.compile(
        r"^No keepalive sent from .*? for (\d+) seconds"
    )
    keepalive_ok_line_pattern = re.compile(r"Keepalive last sent from")
    timeout_line_pattern = re.compile(
        r"^Execution timed out|Unable to TERM.KILL the process"
    )
    graphite_line_pattern = re.compile(r"^([^\s]+) ([^\s]+) \d+$")

    #     } elsif ( $line =~ m/^No keepalive sent from .*? for (\d+) seconds / ) {
    #     $summary    = "Sensu agent offline - No communication for " . ( sprintf( "%.1f", $1 / 60 ) ) . " mins";
    #     $team       = "SysAut";
    #     $severity   = "Major";
    #     $id         = "Sensu agent offline";
    #     $check_type = "keepalive";
    #     $expiry     = 130;
    #   } elsif ( $line =~ m/^Execution timed out|Unable to TERM.KILL the process/ ) {

    # Loop through the check output and pull out all the lines that conform to the alert pattern
    for check_line in check_output:
        alert_line_match = alert_line_pattern.match(check_line)
        success_line_match = success_line_pattern.match(check_line)
        no_keepalive_line_match = no_keepalive_line_pattern.match(check_line)
        timeout_line_match = timeout_line_pattern.match(check_line)
        graphite_line_match = graphite_line_pattern.match(check_line)
        keepalive_ok_line_match = keepalive_ok_line_pattern.match(check_line)

        alert_attributes = {}

        # Ignore blank lines
        if check_line == "":
            continue

        if alert_line_match:
            alert_attributes = alert_line_match.groupdict()

            # Alter the key so that it doesnt contain any forward slashes
            alert_attributes["key"] = alert_attributes["key"].replace("/", "_")
        elif success_line_match:
            continue
        elif no_keepalive_line_match:
            alert_attributes["summary"] = (
                "Sensu agent offline ",
                f"- No communication for {(no_keepalive_line_match.group(1)/60):.1f} mins",
            )
            alert_attributes["monitor_name"] = "keepalive"
            alert_attributes["team"] = "SysAut"
            alert_attributes["severity"] = "Major"
            alert_attributes["key"] = "Sensu agent offline"
            alert_attributes["ttl"] = 130

        elif keepalive_ok_line_match:
            alert_attributes["summary"] = "CLEAR - Sensu agent is now online"
            alert_attributes["monitor_name"] = "keepalive"
            alert_attributes["team"] = "SysAut"
            alert_attributes["severity"] = "Clear"
            alert_attributes["key"] = "Sensu agent offline"

        elif timeout_line_match:
            # Skip timeouts until they have happened 3 times in a row
            if json_object["check"]["occurrences"] < 3:
                logging.debug("Ignoring timeout until there have been 3 occurrences")
                continue

            alert_attributes["summary"] = (
                f"Timeout running - {json_object['check']['metadata']['name']} ",
                f"- Monitor frequency is: {(json_object['check']['interval']/60):.1f} mins.",
            )
            alert_attributes["monitor_name"] = "timeout"
            alert_attributes["key"] = json_object["check"]["metadata"]["name"]
            alert_attributes["team"] = "SysAut"
            alert_attributes["severity"] = "Minor"
            alert_attributes["ttl"] = json_object["check"]["interval"] + 15
        elif graphite_line_match:
            # Ignore anything that's graphite metrics
            continue
        else:
            # This is an unhandled format, output a generic message
            alert_attributes["summary"] = (
                "Invalid Sensu check result",
                f"- {json_object['check']['metadata']['name']} - {check_line}",
            )
            alert_attributes["team"] = "SysAut"
            alert_attributes["severity"] = "Minor"
            alert_attributes["ttl"] = json_object["check"]["interval"] + 15

        # Default using the entity name as the source
        if "source" not in alert_attributes:
            alert_attributes["source"] = json_object["entity"]["metadata"]["name"]
        if "monitor_name" not in alert_attributes:
            alert_attributes["monitor_name"] = ""

        # Get the environment value from the entity labels
        alert_attributes["environment"] = json_object["entity"]["metadata"]["labels"][
            "environment"
        ]

        if re.search(
            r"(check.*has not run recently|Metric check.*is erroring)",
            alert_attributes["summary"],
        ):
            alert_attributes["ttl"] = json_object["check"]["interval"] + 10

        # If the alert is clearing, then append this to the start of the summary
        if (
            "severity" not in alert_attributes
            or not alert_attributes["severity"]
            or alert_attributes["severity"] == "Clear"
        ):
            alert_attributes["summary"] = f"CLEAR - {alert_attributes['summary']}"
            alert_attributes["severity"] = "Clear"

        if alert_attributes["environment"].lower() == "prod":
            alert_attributes["environment"] = "Production"

        # BEFORE sending anything, we need to determine exactly to send based on the status of the message
        # Check in DynamoDB for a matching key

        alert_key = f"{alert_attributes['monitor_name']}_{alert_attributes['key']}_{alert_attributes['source']}"

        skip_alert = False
        logging.debug(f"Seaching DynamoDB for {alert_key}")
        table_item = ddb_table.get_item(Key={"alert_key": alert_key})

        # Handle expiry properly now
        ttl = DEFAULT_TTL
        if (
            "interval" in alert_attributes
            and alert_attributes["interval"] > 0
            and "ttl" not in alert_attributes
        ):
            ttl = alert_attributes["interval"] * 3
        ttl = max(ttl, 10)
        alert_attributes["ttl"] = ttl

        logging.debug(f"Alert attributes: {alert_attributes}")

        # logging.debug(f"DynamoDB item: {table_item}")
        if "Item" in table_item:
            existing_event = table_item["Item"]
            logging.debug(
                f"Found existing entry with severity {existing_event['severity']}. Current severity is {alert_attributes['severity']}"
            )

            # If the previous severity is different, and the new severity isnt a clear, send a clear for the previous severity

            if (
                existing_event["severity"] != alert_attributes["severity"]
                and alert_attributes["severity"] != "Clear"
            ):
                logging.debug(
                    f"Sending clear for original {existing_event['severity']} severity"
                )

                cloned_attributes = deepcopy(alert_attributes)
                cloned_attributes["severity"] = "Clear"
                send_response = send_to_sqs(sqs_queue, alert_key, cloned_attributes)
                logging.debug(send_response)

            elif alert_attributes["severity"] == "Clear":
                # Delete the event from the table
                ddb_table.delete_item(Key={"alert_key": alert_key})

            # Now we can send the actual alert
            if alert_attributes["severity"] != "Clear":
                # Reinsert the event into the table so the TTL and severity is updated
                logging.debug("Updating existing entry")
                put_event_in_db(ddb_table, alert_key, alert_attributes)

        else:
            # If this isnt a clear, we need to
            #  insert a new value into the DB

            if alert_attributes["severity"] != "Clear":
                logging.debug("Inserting new entry")

                put_event_in_db(ddb_table, alert_key, alert_attributes)
            else:
                if (
                    alert_attributes["monitor_name"] == "SensuHB"
                    or alert_attributes["monitor_name"] != "MetricsStatus:"
                ):
                    logging.debug("Skipping sending trap for already cleared alert")
                    skip_alert = True
                else:
                    # Severity always needs to be at Info level so it doesnt clear
                    alert_attributes["severity"] = "Info"

        if not skip_alert:
            # Send the alert to the SQS queue
            send_response = send_to_sqs(sqs_queue, alert_key, alert_attributes)
            logging.debug(send_response)

        logging.debug("")
    return 0


if __name__ == "__main__":
    logging.getLogger("boto3").setLevel(logging.WARNING)
    logging.getLogger("botocore").setLevel(logging.WARNING)
    logging.getLogger("nose").setLevel(logging.WARNING)
    logging.getLogger("s3transfer").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    start_time = round(time.time() * 1000)
    RC = main()
    end_time = round(time.time() * 1000)
    write_log_file(f"{end_time - start_time} ms")
    sys.exit(RC)
