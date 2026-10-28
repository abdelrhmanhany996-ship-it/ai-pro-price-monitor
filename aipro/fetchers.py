"""Shared fetch types and the HTTP client (honest User-Agent, no protection bypass)."""
import gzip
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from decimal import Decimal

USER_AGENT = "AIProPriceMonitor/1.0 (+personal price tracker; respects blocks)"


class FetchError(Exception):
    """kind: network | blocked | rate_limited | parse | currency"""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class PriceResult:
    price: Decimal
    currency: str
    kind: str = "base"       # base = product price; final = incl. fees
    note: str = ""


def http_get(url: str, timeout: int = 20, retries: int = 2) -> str:
    """GET with a short retry on transient network errors (blocks/429/HTTP errors are not retried)."""
    for attempt in range(retries + 1):
        try:
            return _get(url, timeout)
        except FetchError as e:
            if e.kind != "network" or attempt == retries:
                raise
            time.sleep(2 * (attempt + 1))


def _get(url: str, timeout: int) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read(5_000_000)
            if r.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise FetchError("rate_limited", "HTTP 429") from None
        if e.code in (401, 403, 451):
            raise FetchError("blocked", f"HTTP {e.code} (الموقع يمنع الوصول الآلي)") from None
        raise FetchError("network", f"HTTP {e.code}") from None
    except urllib.error.URLError as e:
        raise FetchError("network", f"URLError: {str(e.reason)[:80]}") from None
    except Exception as e:
        raise FetchError("network", type(e).__name__) from None
    return raw.decode("utf-8", "replace")
