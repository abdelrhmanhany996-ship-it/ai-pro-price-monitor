import logging
import os
import re

_TOKEN_RE = re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{30,}\b")


class RedactFilter(logging.Filter):
    """Masks the bot token (exact value and token-shaped strings) in every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        if token:
            msg = msg.replace(token, "***")
        record.msg, record.args = _TOKEN_RE.sub("***", msg), ()
        return True


def setup(level: str = "INFO") -> None:
    h = logging.StreamHandler()
    h.addFilter(RedactFilter())
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [h]
    root.setLevel(level)
