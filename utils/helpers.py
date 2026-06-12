"""General utility helpers."""

import logging
import subprocess
from pathlib import Path
from datetime import datetime


def setup_logger(name: str, log_dir: Path) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    log_file = log_dir / f"{datetime.now():%Y%m%d}.log"
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)

    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%H:%M:%S",
    )
    fh.setFormatter(fmt)
    ch.setFormatter(fmt)

    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


def get_timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def probe_video(path: Path) -> bool:
    """Return True if ffprobe can extract a valid duration (moov atom present)."""
    try:
        r = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True, text=True, timeout=10,
        )
        return r.returncode == 0 and bool(r.stdout.strip())
    except Exception:
        return False
