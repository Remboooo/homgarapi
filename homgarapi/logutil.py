import logging
from pathlib import Path

TRACE = logging.DEBUG - 1


def get_logger(file: str):
    return logging.getLogger(Path(__file__).stem)
