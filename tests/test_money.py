from decimal import Decimal

import pytest

from aipro.money import fmt_amount, parse_price


@pytest.mark.parametrize("text,value,cur", [
    ("199 EGP", "199", "EGP"), ("EGP 199", "199", "EGP"), ("$5.28", "5.28", "USD"),
    ("5,28", "5.28", None), ("1,299.50 EGP", "1299.50", "EGP"), ("1.299,50 جنيه", "1299.50", "EGP"),
    ("١٩٩ ج.م", "199", "EGP"), ("1,299", "1299", None), ("US$ 3.30", "3.30", "USD"),
    ("1 299,00 EGP", "1299.00", "EGP"),
])
def test_parse(text, value, cur):
    assert parse_price(text) == (Decimal(value), cur)


@pytest.mark.parametrize("bad", ["", "   ", "N/A", "free", "0", "0.00 EGP", "—"])
def test_unreadable_or_zero_is_error_not_zero(bad):
    with pytest.raises(ValueError):
        parse_price(bad)


def test_fmt():
    assert fmt_amount(Decimal("199"), "EGP") == "199 EGP"
    assert fmt_amount(Decimal("3.3"), "USD") == "3.30 USD"
    assert fmt_amount(Decimal("5"), "USD") == "5.00 USD"
    assert fmt_amount(Decimal("158.4"), "EGP") == "158.40 EGP"
