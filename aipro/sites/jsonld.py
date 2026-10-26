import json
import re

from ..fetchers import FetchError, PriceResult
from ..money import normalize_number

_LD = re.compile(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.S | re.I)


def _walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def _offers(node, use_low):
    """(price, currency) pairs found under one JSON-LD node."""
    out = set()
    for n in _walk(node):
        if "priceCurrency" not in n:
            continue
        raw = n.get("price", n.get("lowPrice"))
        if raw is None:
            continue
        try:
            lo = normalize_number(str(raw))
            hi = lo if use_low else normalize_number(str(n.get("highPrice", raw)))
        except ValueError:
            continue
        if lo != hi:
            raise FetchError("parse", f"عدة أسعار مختلفة في الصفحة (من {lo} إلى {hi} {n['priceCurrency']}) — تحتاج مراجعة")
        out.add((lo, str(n["priceCurrency"]).upper()))
    return out


def parse_product_offer(html: str, use_low: bool = False, url_hint: str | None = None) -> PriceResult:
    """Read schema.org Product offers. With several Product blocks, url_hint picks the page's own.
    Raises FetchError(parse) if the price is still ambiguous — never guesses."""
    blocks = []
    for m in _LD.finditer(html):
        try:
            data = json.loads(m.group(1))
        except ValueError:
            continue
        blocks += [n for n in _walk(data) if str(n.get("@type", "")).lower() == "product"]
    if url_hint and len(blocks) > 1:
        mine = [b for b in blocks if url_hint in json.dumps(b, ensure_ascii=False)]
        blocks = mine or blocks
    prices = set()
    for b in blocks:
        prices |= _offers(b, use_low)
    if len(prices) != 1:
        found = ", ".join(f"{p} {c}" for p, c in sorted(prices)[:6])
        raise FetchError("parse", "لم يُعثر على سعر واضح في بيانات المنتج" if not prices
                         else f"أكثر من سعر/عملة في الصفحة ({found}) — تحتاج مراجعة")
    price, cur = prices.pop()
    return PriceResult(price, cur)
