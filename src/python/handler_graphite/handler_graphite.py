#!/usr/bin/env python
"""Sensu Handler for pushing metrics to Graphite."""
import argparse
import json
import logging
import socket
import sys

from sensu_plugin import EnvDefault, SensuAsset


class HandlerGraphite(SensuAsset):  # pylint: disable=too-few-public-methods
    """This class picks up metrics from STDIN, passed from Sensu, and sends them to Graphite."""

    def __init__(self) -> None:
        """Initialise the class."""
        # Call the parent init
        super().__init__()
        self.args = self._parse_cli_args()
        if self.args.verbose:
            logging.getLogger().setLevel(logging.DEBUG)

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
            "--host",
            required=False,
            help="graphite host to send metrics",
            default="127.0.0.1",
            action=EnvDefault,
            envvar="GRAPHITE_HOST",
        )
        parser.add_argument(
            "-p",
            "--port",
            required=False,
            help="graphite port",
            default=2003,
            action=EnvDefault,
            envvar="GRAPHITE_PORT",
        )

        return parser.parse_args()

    def run(self) -> None:
        """Run the handler."""
        # Parse event data from STDIN
        stdin_event = ""
        for line in sys.stdin:
            stdin_event.join(line)

        # Connect to the graphite port
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as socket_:
            socket_.connect((self.args.host, int(self.args.port)))

            # Write STDIN to /tmp
            with open(
                "/tmp/event.json", "w", encoding="utf-8"  # nosec B108
            ) as tmp_file:
                tmp_file.write(stdin_event)

            # Parse the event into JSON format
            json_object = json.loads(stdin_event)

            # Extract the metric points
            if not (metrics := json_object["metrics"]["points"]):
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
            socket_.sendall(output_string.encode("utf-8"))


if __name__ == "__main__":
    HandlerGraphite()
