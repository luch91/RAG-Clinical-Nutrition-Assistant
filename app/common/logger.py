import logging
import os
import re
import sys
from datetime import datetime

LOGS_DIR = "logs"
os.makedirs(LOGS_DIR, exist_ok=True)

LOG_FILE = os.path.join(LOGS_DIR, f"log_{datetime.now().strftime('%Y-%m-%d')}.log")

# ANSI escape sequence regex to strip color codes from logs
ANSI_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")


class StripAnsiFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if isinstance(record.msg, str):
                record.msg = ANSI_RE.sub("", record.msg)
        except Exception:
            pass
        return True


_configured = False


def _configure_root_logger():
    global _configured
    if _configured:
        return

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    fmt = logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s")
    ansi_filter = StripAnsiFilter()

    # File handler with UTF-8 encoding
    try:
        fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
        fh.setLevel(logging.INFO)
        fh.setFormatter(fmt)
        fh.addFilter(ansi_filter)
        root.addHandler(fh)
    except Exception:
        # Fallback to basicConfig if FileHandler fails
        logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    # Console handler for dev visibility
    sh = logging.StreamHandler(stream=sys.stdout)
    sh.setLevel(logging.INFO)
    sh.setFormatter(fmt)
    sh.addFilter(ansi_filter)
    root.addHandler(sh)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    _configure_root_logger()
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    return logger
