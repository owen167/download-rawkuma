from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path


_SECRET_PATTERNS = (
    re.compile(r"(?i)(?P<key>discord[_-]?token|gofile[_-]?token|api[_-]?key|authorization|cookie)(?P<sep>\s*[:=]\s*)(?P<value>[^\s,;]+)"),
    re.compile(r"(?i)(?P<prefix>Bearer\s+)(?P<value>[^\s]+)"),
)


class RedactSecrets(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        for pattern in _SECRET_PATTERNS:
            def replace(match: re.Match[str]) -> str:
                groups = match.groupdict()
                if "key" in groups:
                    return f"{groups['key']}{groups['sep']}[REDACTED]"
                return f"{groups['prefix']}[REDACTED]"
            message = pattern.sub(replace, message)
        record.msg = message
        record.args = ()
        return True


def setup_logging(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    redactor = RedactSecrets()
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for handler in root.handlers[:]:
        root.removeHandler(handler)
        handler.close()

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.addFilter(redactor)
    file_handler = RotatingFileHandler(log_dir / "rawkuma-bot.log", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.addFilter(redactor)
    error_handler = RotatingFileHandler(log_dir / "errors.log", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    error_handler.addFilter(redactor)
    root.addHandler(console)
    root.addHandler(file_handler)
    root.addHandler(error_handler)
    logging.getLogger("discord.http").setLevel(logging.INFO)
    logging.getLogger("discord.gateway").setLevel(logging.INFO)
