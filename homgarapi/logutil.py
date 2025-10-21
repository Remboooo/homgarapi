"""Logging helpers for the HomGar API package."""

import logging
from pathlib import Path

TRACE = logging.DEBUG - 1
"""Custom TRACE logging level used by the HomGar client."""


def get_logger(file: str) -> logging.Logger:
    """Return a module-level logger by stem name of the provided path.

    :param file: File path whose stem will be used as the logger name.
    :returns: A logger instance tied to the provided filename stem.
    """
    return logging.getLogger(Path(file).stem)
