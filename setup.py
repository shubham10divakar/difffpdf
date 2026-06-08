"""Compatibility shim.

All project metadata lives in ``pyproject.toml`` (PEP 621). This file exists
only so legacy tooling and ``python setup.py ...`` invocations keep working;
setuptools reads the configuration from pyproject.toml automatically.
"""

from setuptools import setup

setup()
