from ..fetchers import FetchError, PriceResult, http_get
from .jsonld import parse_product_offer

URL = "https://www.maads.io/catalog/google-ai-pro-18"
FALLBACK_URL = "https://maads.io/catalog/google-ai-pro-18"


def parse(html: str) -> PriceResult:
    r = parse_product_offer(html)
    if r.currency != "EGP":
        raise FetchError("currency", f"العملة المعروضة {r.currency} وليست EGP — تحتاج مراجعة")
    return r


def fetch() -> PriceResult:
    try:
        return parse(http_get(URL))
    except FetchError as e:
        if e.kind != "network":
            raise
        return parse(http_get(FALLBACK_URL))     # other host name if the primary is unreachable
