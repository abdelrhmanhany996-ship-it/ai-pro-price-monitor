import json
import logging
import re
from decimal import Decimal

from ..fetchers import FetchError, PriceResult, http_get
from .jsonld import parse_product_offer

log = logging.getLogger("aipro.driffle")
URL = "https://driffle.com/google-ai-pro-gemini-18-months-trial-global-digital-key-p9998937"
STORE_URL = ("https://driffle.com/store?q=Google%20AI%20Pro%20-%20Gemini%2018%20Months%20(Global)"
             "%20-%20Activation%20Link")
# Driffle prices by visitor location (the VPS sees EUR). We take the cheapest offer in whatever
# currency is shown and convert it to EGP for display/alerts.
CURRENCY = "ANY"
SUPPORTED = ("EGP", "USD", "EUR")
_NEXT = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def _check_blocked(html: str) -> None:
    if re.search(r"<title>\s*Blocked\b", html, re.I):
        raise FetchError("blocked", "Driffle يحجب الطلبات الآلية (صفحة Blocked)")


def parse(html: str) -> PriceResult:
    """Product page: cheapest offer from schema.org data (0 means 'no offers' and is ignored)."""
    _check_blocked(html)
    r = parse_product_offer(html, use_low=True, pick_min=True)
    if r.currency not in SUPPORTED:
        raise FetchError("currency", f"العملة المعروضة {r.currency} غير مدعومة — تحتاج مراجعة")
    return PriceResult(r.price, r.currency, "base", "أرخص عرض في الصفحة")


def _walk(n):
    if isinstance(n, dict):
        yield n
        for v in n.values():
            yield from _walk(v)
    elif isinstance(n, list):
        for v in n:
            yield from _walk(v)


def _currency_of(node: dict, data) -> str | None:
    for k in ("currency", "currencyCode", "priceCurrency"):
        if isinstance(node.get(k), str):
            return node[k].upper()
    found = {str(n[k]).upper() for n in _walk(data) for k in ("currency", "currencyCode")
             if isinstance(n.get(k), str) and len(n[k]) == 3}
    return found.pop() if len(found) == 1 else None


def store_matches(html: str):
    m = _NEXT.search(html)
    if not m:
        raise FetchError("parse", "بيانات صفحة البحث غير موجودة")
    data = json.loads(m.group(1))
    out = []
    for n in _walk(data):
        price = n.get("price")
        if not isinstance(price, (int, float)) or price <= 0:
            continue
        text = " ".join(v for v in n.values() if isinstance(v, str)).lower()
        if "google ai pro" in text and "18 month" in text:
            out.append((n, Decimal(str(price))))
    return data, out


def parse_store(html: str) -> PriceResult:
    """Search page: cheapest 'Google AI Pro … 18 Months' listing."""
    _check_blocked(html)
    data, matches = store_matches(html)
    if not matches:
        raise FetchError("parse", "لم يُعثر على المنتج في صفحة البحث")
    node, price = min(matches, key=lambda x: x[1])
    cur = _currency_of(node, data)
    if cur not in SUPPORTED:
        raise FetchError("currency", f"عملة صفحة البحث غير معروفة ({cur}) — تحتاج مراجعة")
    return PriceResult(price, cur, "base", "أرخص عرض في صفحة البحث")


def fetch() -> PriceResult:
    try:
        return parse(http_get(URL))
    except FetchError as first:
        if first.kind not in ("parse",):
            raise
    html = http_get(STORE_URL)
    try:
        return parse_store(html)
    except FetchError:
        _diagnose(html)                      # temporary: shows how listings look so the parser can adapt
        raise


def _diagnose(html: str) -> None:
    try:
        data, matches = store_matches(html)
    except Exception as e:
        log.warning("DIAG store parse error: %s", type(e).__name__)
        return
    log.warning("DIAG matches=%d", len(matches))
    for n, p in matches[:3]:
        short = {k: (v if not isinstance(v, (dict, list)) else type(v).__name__) for k, v in n.items()}
        log.warning("DIAG node: %s", json.dumps(short, ensure_ascii=False)[:600])
    cur = sorted({str(n[k]) for n in _walk(data) for k in ("currency", "currencyCode") if isinstance(n.get(k), str)})
    log.warning("DIAG currencies=%s", cur[:10])
