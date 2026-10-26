from decimal import Decimal

import pytest

from aipro import fx as fxmod
from aipro.db import DB
from aipro.engine import Engine
from aipro.outbox import Outbox
from aipro.products import Product
from conftest import T0, feed, msgs


@pytest.fixture
def eng(cfg, tmp_path):
    prods = {"driffle": Product("driffle", "Driffle", "https://example.test/d", "EUR", lambda: None),
             "maads": Product("maads", "MAADS", "https://example.test/m", "EGP", lambda: None)}
    db = DB(str(tmp_path / "e.db"))
    e = Engine(cfg, db, prods, Outbox(db))
    fxmod.save(db, fxmod.Rate(Decimal("50"), "test-fx", T0, T0, Decimal("55")))   # fake rates
    return e


def test_eur_below_limit_after_conversion_alerts(eng):
    feed(eng, "driffle", "3.60")      # 3.60 * 55 = 198
    a = msgs(eng, "alert")
    assert len(a) == 1 and "3.60 EUR" in a[0]["text"] and "198 EGP" in a[0]["text"]


def test_eur_exactly_200_or_more_no_alert(eng):
    feed(eng, "driffle", "4")         # 220
    assert msgs(eng, "alert") == []


def test_eur_without_rate_not_judged_and_shown_as_unavailable(eng):
    eng.db.set("fx_eur", "")
    feed(eng, "driffle", "1.00")
    assert msgs(eng, "alert") == [] and "غير متاح" in eng.prices_text(T0)


def test_eur_change_report_shows_original_and_egp(eng):
    feed(eng, "driffle", "7.00")
    feed(eng, "driffle", "6.50", now=T0 + 1)
    t = msgs(eng, "change")[0]["text"]
    assert "6.50 EUR" in t and "357.50 EGP" in t and "1 EUR = 55.0000 EGP" in t
