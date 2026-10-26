"""Price/number parsing that never guesses: raises ValueError when unreadable."""
import re
from decimal import Decimal, InvalidOperation

_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩٫٬", "0123456789.,")
_NUM = re.compile(r"\d[\d.,\s ]*\d|\d")
_CURRENCIES = [
    (re.compile(r"\bEGP\b|\bE£|£E\b|\bLE\b|ج\.?\s?م|جنيه", re.I), "EGP"),
    (re.compile(r"\bUSD\b|US\$|\$", re.I), "USD"),
    (re.compile(r"\bEUR\b|€", re.I), "EUR"),
]


def normalize_number(token: str) -> Decimal:
    t = re.sub(r"[\s ]", "", token.translate(_ARABIC_DIGITS))
    if not t or not re.fullmatch(r"[\d.,]+", t):
        raise ValueError(f"unreadable number: {token!r}")
    if "," in t and "." in t:
        dec = "," if t.rfind(",") > t.rfind(".") else "."
        thou = "." if dec == "," else ","
        t = t.replace(thou, "").replace(dec, ".")
    elif "," in t:
        parts = t.split(",")
        if len(parts) > 2 or len(parts[-1]) == 3:
            t = t.replace(",", "")      # 1,299 / 1,299,000 -> thousands
        else:
            t = t.replace(",", ".")     # 5,28 -> decimal
    elif t.count(".") > 1:
        t = t.replace(".", "")
    try:
        value = Decimal(t)
    except InvalidOperation:
        raise ValueError(f"unreadable number: {token!r}") from None
    if value <= 0:
        raise ValueError(f"non-positive price: {token!r}")
    return value


def detect_currency(text: str) -> str | None:
    for rx, code in _CURRENCIES:
        if rx.search(text):
            return code
    return None


def parse_price(text: str) -> tuple[Decimal, str | None]:
    """'199 EGP' / 'EGP 199' / '$5.28' / '5,28' -> (Decimal, currency|None)."""
    if not text or not text.strip():
        raise ValueError("empty price text")
    m = _NUM.search(text.translate(_ARABIC_DIGITS))
    if not m:
        raise ValueError(f"no number in {text!r}")
    return normalize_number(m.group(0)), detect_currency(text)


def fmt_amount(value: Decimal, currency: str) -> str:
    v = value.quantize(Decimal("0.01"))
    s = f"{v:,.2f}"
    if currency == "EGP" and s.endswith(".00"):
        s = s[:-3]
    return f"{s} {currency}"
