import re

from ..fetchers import FetchError, PriceResult, http_get
from ..money import normalize_number

URL = "https://www.z2u.com/product-900686/Google-AI-Gemini-Pro-18-Months-Private-Account.html"
_MB = re.compile(r"""class=['"]mbprice['"][^>]*>\s*([\d.,]+)\s*<""")
_UNIT = re.compile(r"""1\s*=\s*([A-Z]{3})\s*\$?\s*<span[^>]*class=['"]ut_price['"][^>]*>\s*([\d.,]+)\s*<""")


def parse(html: str) -> PriceResult:
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
    return PriceResult(values.pop(), cur, "base", "السعر لا يشمل رسوم الدفع")


def fetch() -> PriceResult:
    return parse(http_get(URL))
