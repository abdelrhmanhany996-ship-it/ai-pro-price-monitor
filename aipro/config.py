import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path


def load_dotenv(path: str = ".env") -> None:
    """Load KEY=VALUE pairs from .env without overriding real environment variables."""
    p = Path(path)
    if not p.is_file():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if " #" in v:
            v = v.split(" #", 1)[0]
        os.environ.setdefault(k.strip(), v.strip().strip("'\""))


@dataclass(frozen=True)
class Settings:
    token: str = ""
    chat_id: str = ""
    track_base_url: str = ""
    web_host: str = "127.0.0.1"
    web_port: int = 8080
    check_interval: int = 300
    reminder_interval: int = 600
    threshold_egp: Decimal = Decimal("200")
    confirm_checks: int = 2
    error_alert_after: int = 3
    max_stale: int = 1800
    daily_time: str = "21:00"
    timezone: str = "Africa/Cairo"
    fx_refresh: int = 3600
    fx_max_age: int = 48 * 3600
    db_path: str = "data/aipro.db"
    log_level: str = "INFO"

    @property
    def telegram_ready(self) -> bool:
        return bool(self.token and self.chat_id)


def load() -> Settings:
    load_dotenv()
    g = os.environ.get
    return Settings(
        token=g("TELEGRAM_BOT_TOKEN", "").strip(),
        chat_id=g("TELEGRAM_CHAT_ID", "").strip(),
        track_base_url=g("TRACK_BASE_URL", "").strip().rstrip("/"),
        web_host=g("WEB_HOST", "127.0.0.1"),
        web_port=int(g("WEB_PORT", "8080")),
        check_interval=int(g("CHECK_INTERVAL_SECONDS", "300")),
        reminder_interval=int(g("REMINDER_INTERVAL_SECONDS", "600")),
        threshold_egp=Decimal(g("THRESHOLD_EGP", "200")),
        confirm_checks=max(1, int(g("CONFIRM_CHECKS", "2"))),
        error_alert_after=max(1, int(g("ERROR_ALERT_AFTER", "3"))),
        max_stale=int(g("MAX_STALE_SECONDS", "1800")),
        daily_time=g("DAILY_REPORT_TIME", "21:00"),
        timezone=g("TIMEZONE", "Africa/Cairo"),
        fx_refresh=int(g("FX_REFRESH_SECONDS", "3600")),
        fx_max_age=int(g("FX_MAX_AGE_HOURS", "48")) * 3600,
        db_path=g("DB_PATH", "data/aipro.db"),
        log_level=g("LOG_LEVEL", "INFO").upper(),
    )
