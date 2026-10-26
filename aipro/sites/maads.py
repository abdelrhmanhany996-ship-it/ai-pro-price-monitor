from ..fetchers import FetchError, PriceResult, http_get
from .jsonld import parse_product_offer

URL = "https://maads.io/catalog/google-ai-pro-18"


def parse(html: str) -> PriceResult:
    r = parse_product_offer(html)
    if r.currency != "EGP":
        raise FetchError("currency", f"العملة المعروضة {r.currency} وليست EGP — تحتاج مراجعة")
    return r


def fetch() -> PriceResult:
    return parse(http_get(URL))
