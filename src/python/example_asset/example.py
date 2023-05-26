#!/usr/bin/env python
# ruff: noqa: T201
"""Example python script to be packaged as a Sensu Asset."""

import sys

import bofhexcuse

print("Example using bofhexcuse python module, packaged with this asset")
print("\nHere's the current module search path")
print(sys.path)
print("\nCalling bofhexcuse.bofh_excuse:")
print(
    "This should return without error when called using wrapper script in asset's bin/"
)
print("This should return with error when called directly from asset's libexec/")
print(bofhexcuse.bofh_excuse()[0])
