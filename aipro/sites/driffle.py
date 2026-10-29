import logging
import re

from ..fetchers import FetchError, PriceResult, http_get
from .jsonld import parse_product_offer

log = logging.getLogger("aipro.driffle")
URL = "https://driffle.com/google-ai-pro-gemini-18-months-trial-global-digital-key-p9998937"
# Driffle prices by visitor location (the VPS sees EUR). We take the cheapest offer on the page in
# whatever currency is shown and convert it to EGP for display/alerts.
CURRENCY = "ANY"
SUPPORTED = ("EGP", "USD", "EUR")


def parse(html: str) -> PriceResult:
    if re.search(r"<title>\s*Blocked\b", html, re.I):
        raise FetchError("blocked", "Driffle يحجب الطلبات الآلية (صفحة Blocked)")
    r = parse_product_offer(html, use_low=True, pick_min=True)
    if r.currency not in SUPPORTED:
        raise FetchError("currency", f"العملة المعروضة {r.currency} غير مدعومة — تحتاج مراجعة")
    return PriceResult(r.price, r.currency, "base", "أرخص عرض في الصفحة")


STORE_URL = ("https://driffle.com/store?q=Google%20AI%20Pro%20-%20Gemini%2018%20Months%20(Global)"
             "%20-%20Activation%20Link")


def fetch() -> PriceResult:
    html = http_get(URL)
    try:
        return parse(html)
    except FetchError as e:
        if e.kind == "parse":                     # temporary diagnostics to adapt the parser
            from .diag import summarize
            summarize(html, "product")
            try:
                summarize(http_get(STORE_URL), "store")
            except FetchError as e2:
                log.warning("DIAG store fetch failed: %s", e2)
        raise
