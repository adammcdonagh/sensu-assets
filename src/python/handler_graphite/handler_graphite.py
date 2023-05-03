#!/usr/bin/env python

import argparse
import json
import logging
import socket
import sys


def main() -> int:
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
        "--host",
        required=False,
        help="graphite host to send metrics",
        default="127.0.0.1",
    )
    parser.add_argument(
        "-p",
        "--port",
        required=False,
        help="graphite port",
        default=2003,
    )
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Parse event data from STDIN
    stdin_event = ""
    for line in sys.stdin:
        stdin_event += line

    # Connect to the graphite port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((args.host, int(args.port)))

        # Write STDIN to /tmp
        with open("/tmp/event.json", "w") as fh:
            fh.write(stdin_event)

        # Parse the event into JSON format
        json_object = json.loads(stdin_event)

        # Extract the metric points
        metrics = json_object["metrics"]["points"]
        if not metrics:
            logging.error("No metrics received to process!")
            sys.exit(1)
        output_string = ""
        for point in metrics:
            logging.debug(f"Got point {point}")

            # Append any tags onto the metric name
            metric_name = point["name"]
            for tag in point["tags"]:
                metric_name += f";{tag['name']}={tag['value']}"

            metric_line = f"{metric_name} {point['value']} {point['timestamp']}"
            logging.debug(f"Sending: {metric_line}")
            output_string += f"{metric_line}\n"

        # send metric_name to graphite as bytes
        s.sendall(output_string.encode("utf-8"))


logging.basicConfig(format="%(asctime)s %(levelname)s: %(message)s", level=logging.INFO)
rc = main()
sys.exit(rc)
