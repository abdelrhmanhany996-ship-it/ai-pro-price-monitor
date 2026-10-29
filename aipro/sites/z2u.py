import re
from decimal import Decimal

from ..fetchers import FetchError, PriceResult, http_get
from ..money import normalize_number

URL = "https://www.z2u.com/product-900686/Google-AI-Gemini-Pro-18-Months-Private-Account.html"
CATEGORY_URL = "https://www.z2u.com/gemini/accounts-5-28045?category_son_id=14049"   # Gemini accounts, 18 Months
_MB = re.compile(r"""class=['"]mbprice['"][^>]*>\s*([\d.,]+)\s*<""")
_UNIT = re.compile(r"""1\s*=\s*([A-Z]{3})\s*\$?\s*<span[^>]*class=['"]ut_price['"][^>]*>\s*([\d.,]+)\s*<""")
_CARD = re.compile(r'<a class="productCardStyle-3[^>]*href="(https://[^"]+)"(.*?)(?=<a class="productCardStyle-3|$)', re.S)
_TITLE = re.compile(r'<span class="title">(.*?)</span>', re.S)
_PRICE = re.compile(r'class="priceTxt">\s*([^<]+?)\s*<')
_STRIP = re.compile(r"google ai gemini pro 18 months\s*", re.I)


def parse(html: str) -> PriceResult:
    """Single product page (one listing)."""
    mb, unit = _MB.findall(html), _UNIT.findall(html)
    if not mb or not unit:
        raise FetchError("parse", "لم يُعثر على عنصر السعر في صفحة Z2U")
    values = {normalize_number(x) for x in mb}
    currencies = {c for c, _ in unit}
    if len(values) != 1 or len(currencies) != 1:
        raise FetchError("parse", "أسعار أو عملات متعارضة في الصفحة — تحتاج مراجعة")
    cur = currencies.pop()
    if cur != "USD":
        raise FetchError("currency", f"العملة المعروضة {cur} وليست USD — تحتاج مراجعة")
    if normalize_number(unit[0][1]) != next(iter(values)):
        raise FetchError("parse", "السعر لا يطابق سعر الوحدة — تحتاج مراجعة")
    return PriceResult(values.pop(), cur, "base", "Private Account · السعر لا يشمل رسوم الدفع")


def parse_category(html: str) -> PriceResult:
    """Category page: cheapest 'from' price among the listed 18-month Gemini products."""
    cards = []
    for href, body in _CARD.findall(html):
        t, p = _TITLE.search(body), _PRICE.search(body)
        if not (t and p) or "$" not in p.group(1):          # only USD "$x.xx" prices are trusted
            continue
        try:
            price = normalize_number(p.group(1).replace("$", ""))
        except ValueError:
            continue
        cards.append((price, re.sub(r"\s+", " ", t.group(1)).strip()))
    if not cards:
        raise FetchError("parse", "لم يُعثر على منتجات في صفحة قسم Z2U")
    price, title = min(cards)
    return PriceResult(price, "USD", "base", (_STRIP.sub("", title) or title) + " · أرخص عرض في القسم")


def fetch() -> PriceResult:
    try:
        return parse_category(http_get(CATEGORY_URL))
    except FetchError as e:
        if e.kind == "blocked":
            raise
    return parse(http_get(URL))             # fallback: the single product page
