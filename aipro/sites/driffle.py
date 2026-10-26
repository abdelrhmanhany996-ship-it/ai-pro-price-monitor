import re

from ..fetchers import FetchError, PriceResult, http_get
from .jsonld import parse_product_offer

URL = "https://driffle.com/google-ai-pro-gemini-18-months-trial-global-digital-key-p9998937"
# Driffle prices by visitor location; from the VPS (Brazil) it shows EUR, so EUR is tracked
# and converted to EGP with the exchange rate. The price is the cheapest seller offer.
CURRENCY = "EUR"


def parse(html: str) -> PriceResult:
    if re.search(r"<title>\s*Blocked\b", html, re.I):
        raise FetchError("blocked", "Driffle يحجب الطلبات الآلية (صفحة Blocked)")
    r = parse_product_offer(html, use_low=True)
    if r.currency != CURRENCY:
        raise FetchError("currency", f"العملة المعروضة {r.currency} وليست {CURRENCY} — تحتاج مراجعة")
    return PriceResult(r.price, r.currency, "base", "أرخص عرض بين البائعين")


def fetch() -> PriceResult:
    return parse(http_get(URL))
