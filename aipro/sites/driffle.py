import re

from ..fetchers import FetchError, PriceResult, http_get
from .jsonld import parse_product_offer

URL = "https://driffle.com/google-ai-pro-gemini-18-months-trial-global-digital-key-p9998937"


def parse(html: str) -> PriceResult:
    if re.search(r"<title>\s*Blocked\b", html, re.I):
        raise FetchError("blocked", "Driffle يحجب الطلبات الآلية (صفحة Blocked)")
    r = parse_product_offer(html)
    if r.currency != "EGP":
        raise FetchError("currency", f"العملة المعروضة {r.currency} وليست EGP — تحتاج مراجعة")
    return r


def fetch() -> PriceResult:
    return parse(http_get(URL))
