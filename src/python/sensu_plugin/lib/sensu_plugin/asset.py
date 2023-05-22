# -*- coding: utf-8 -*-
"""
This is the base class for all Sensu Assets to build from.

Also includes a custom argparse action to allow for environment variables
"""
import argparse
import os

from sensu_plugin.logging import init_logging


class SensuAsset:  # pylint: disable=too-few-public-methods
    """Base class used by plugins and handlers.

    The base class will always initialise the custom logger
    """

    def __init__(self):
        """Create base class and initialise logging."""
        self.logger = init_logging(__name__)


class EnvDefault(argparse.Action):
    """Custom argparse action to allow for environment variables.

    Found here: https://stackoverflow.com/a/10551190

    Args:
        envvar (str): The environment variable to use
        required (bool): Whether or not this argument is required
        default (str): The default value for this argument
    """

    def __init__(self, envvar, required=True, default=None, **kwargs):
        """Create custom argparse action to allow for environment variable overrides."""
        if not default and envvar:
            if envvar in os.environ:
                default = os.environ[envvar]
        if required and default:
            required = False

        super().__init__(default=default, required=required, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):
        """Call the custom argparse action to allow for environment variable overrides."""
        setattr(namespace, self.dest, values)
