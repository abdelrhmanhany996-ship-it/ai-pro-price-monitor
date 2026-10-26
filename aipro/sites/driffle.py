import re

from ..fetchers import FetchError, PriceResult, http_get
from .jsonld import parse_product_offer

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


def fetch() -> PriceResult:
    return parse(http_get(URL))
