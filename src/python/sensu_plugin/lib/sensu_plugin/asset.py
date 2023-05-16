# -*- coding: utf-8 -*-
"""
    This is the base class for all Sensu Assets to build from
"""
from sensu_plugin.logging import init_logging

# Make an abstract class called xyz


class SensuAsset:  # noqa: PLR903

    """
    Base class used by plugins and handlers
    """

    def __init__(self):
        self.logger = init_logging(__name__)
