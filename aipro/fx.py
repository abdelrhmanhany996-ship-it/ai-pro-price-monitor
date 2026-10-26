"""USD->EGP rate from open.er-api.com (free, daily-updated reference rate)."""
import json
import urllib.request
from dataclasses import dataclass
from decimal import Decimal

from .fetchers import USER_AGENT
from .db import DB

FX_URL = "https://open.er-api.com/v6/latest/USD"


@dataclass(frozen=True)
class Rate:
    rate: Decimal
    source: str
    source_ts: int | None
    fetched_ts: int
    eur: Decimal | None = None      # EUR -> EGP


def fetch_rate(now: int) -> Rate:
    req = urllib.request.Request(FX_URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=15) as r:
        d = json.load(r)
    if d.get("result") != "success":
        raise ValueError("fx api error")
    rate = Decimal(str(d["rates"]["EGP"]))
    if rate <= 0:
        raise ValueError("invalid fx rate")
    eur = None
    if d["rates"].get("EUR"):
        eur = rate / Decimal(str(d["rates"]["EUR"]))
    return Rate(rate, "open.er-api.com", d.get("time_last_update_unix"), now, eur)


def save(db: DB, r: Rate) -> None:
    db.x("INSERT INTO fx(id,rate,source,source_ts,fetched_ts) VALUES(1,?,?,?,?) "
         "ON CONFLICT(id) DO UPDATE SET rate=excluded.rate,source=excluded.source,"
         "source_ts=excluded.source_ts,fetched_ts=excluded.fetched_ts",
         (str(r.rate), r.source, r.source_ts, r.fetched_ts))
    db.set("fx_eur", r.eur if r.eur else "")


def current(db: DB, now: int, max_age: int) -> Rate | None:
    """Latest stored rate, or None when missing/too old (never guess)."""
    row = db.one("SELECT * FROM fx WHERE id=1")
    if not row:
        return None
    ts = row["source_ts"] or row["fetched_ts"]
    if now - ts > max_age:
        return None
    eur = db.get("fx_eur")
    return Rate(Decimal(row["rate"]), row["source"], row["source_ts"], row["fetched_ts"],
                Decimal(eur) if eur else None)
