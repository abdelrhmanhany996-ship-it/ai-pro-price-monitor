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


def parse_product_offer(html: str, use_low: bool = False) -> PriceResult:
    """Read schema.org Product offers. Raises FetchError(parse|currency) if ambiguous."""
    prices = set()
    for m in _LD.finditer(html):
        try:
            data = json.loads(m.group(1))
        except ValueError:
            continue
        for n in _walk(data):
            if "priceCurrency" not in n:
                continue
            raw = n.get("price", n.get("lowPrice"))
            hi = n.get("highPrice", raw)
            if raw is None:
                continue
            try:
                lo, hi = normalize_number(str(raw)), normalize_number(str(hi))
            except ValueError:
                continue
            if use_low:
                hi = lo                      # AggregateOffer: cheapest listed offer
            if lo != hi:
                raise FetchError("parse", f"عدة أسعار مختلفة في الصفحة (من {lo} إلى {hi} {n['priceCurrency']}) — تحتاج مراجعة")
            prices.add((lo, str(n["priceCurrency"]).upper()))
    if len(prices) != 1:
        raise FetchError("parse", "لم يُعثر على سعر واضح في بيانات المنتج" if not prices
                         else "أكثر من سعر/عملة في الصفحة — تحتاج مراجعة")
    price, cur = prices.pop()
    return PriceResult(price, cur)
