import logging
from pathlib import Path

TRACE = logging.DEBUG - 1


def get_logger(file: str) -> logging.Logger:
    return logging.getLogger(Path(file).stem)
