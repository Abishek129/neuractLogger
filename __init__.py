"""
Neuract Logger package.

This package contains a simple command???line application for configuring
and running simulated PLC data logging tasks.  See :mod:`plc_logger.main`
for the executable entry point.
"""

from .main import LoggerApp

__all__ = ["LoggerApp"]
