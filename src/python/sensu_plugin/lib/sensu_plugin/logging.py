# -*- coding: utf-8 -*-
"""Simple logging module for the Sensu plugin.

This includes the ability to write to a log file using an
environment variable named SENSU_ASSET_LOG_FILE_PATH
"""
import logging
import os
from sys import stderr

LOG_FORMAT = "%(asctime)s %(levelname)s - %(message)s (%(filename)s:%(lineno)d)"
ASSET_LOG = "asset-log"


class CustomFormatter(logging.Formatter):
    """Custom formatter for the Sensu plugin.

    This will colorize the output based on the log level

    Args:
        logging (logging.Formatter): The logging formatter to use
    """

    grey = "\x1b[0;37m"
    green = "\x1b[1;32m"
    yellow = "\x1b[1;33m"
    red = "\x1b[1;31m"
    purple = "\x1b[1;35m"
    blue = "\x1b[1;34m"
    light_blue = "\x1b[1;36m"
    reset = "\x1b[0m"
    blink_red = "\x1b[5m\x1b[1;31m"

    FORMATS = {
        logging.DEBUG: light_blue + LOG_FORMAT + reset,
        logging.INFO: LOG_FORMAT,
        logging.WARNING: yellow + LOG_FORMAT + reset,
        logging.ERROR: red + LOG_FORMAT + reset,
        logging.CRITICAL: blink_red + LOG_FORMAT + reset,
    }

    def format(self, record):
        """Format the log message."""
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt)
        return formatter.format(record)


def init_logging(name: str, log_level: str = logging.INFO) -> None:
    """
    Initialize logging for the script.

    Args:
        name (str): The name of the logger
        log_level (str): The log level to use for the logger
    """
    # Set the log format
    formatter = CustomFormatter()

    # Check if there's a root logger already
    if not logging.getLogger().hasHandlers():
        # Set the root logger
        logging.basicConfig(
            level=logging.INFO,
        )

        # Remove all existing handlers from the root logger
        logging.getLogger().handlers = []

        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        logging.getLogger().addHandler(stream_handler)

        # Also create a logger for writing a log file, named "asset-log"
        asset_log = logging.getLogger(ASSET_LOG)
        asset_log.setLevel(log_level)

        # Add a handler to write to a log file only
        # Ensure there are no other handlers
        asset_log.handlers = []
        # Pull the log file name from environment variables. If there's one called
        # SENSU_ASSET_LOG_FILE_PATH

        log_file_path = os.environ.get("SENSU_ASSET_LOG_FILE_PATH")
        valid_log_file_path = _check_log_file_path(log_file_path)

        if valid_log_file_path:
            handler = logging.FileHandler(log_file_path)
            handler.setFormatter(formatter)
            asset_log.addHandler(handler)

    return logging.getLogger(f"{name}")


def _check_log_file_path(log_file_path: str) -> bool:
    if log_file_path:
        # If the path is defined, and we can write to that path
        if not os.path.isdir(os.path.dirname(log_file_path)):
            # We don't want to kill the script if the log file can't be written to. instead we just write to stderr
            print(f"ERROR: {log_file_path} is not a directory", file=stderr)
            return False
        if (
            not os.path.exists(log_file_path)
            and not os.access(os.path.dirname(log_file_path), os.W_OK)
        ) or (os.path.exists(log_file_path) and not os.access(log_file_path, os.W_OK)):
            print(f"ERROR: {log_file_path} is not writable", file=stderr)
            return False
        return True
    return False


def write_log_file(log_message: str):
    """
    Write a log message to the log file.

    Args:
        log_message (str): The message to write to the log file
    """
    logging.getLogger(ASSET_LOG).info(log_message)
