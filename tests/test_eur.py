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
    assert msgs(eng, "alert") == [] and "n/a" in eng.prices_text(T0)


def test_eur_change_report_shows_original_and_egp(eng):
    feed(eng, "driffle", "7.00")
    feed(eng, "driffle", "6.50", now=T0 + 1)
    t = msgs(eng, "change")[0]["text"]
    assert "6.50 EUR" in t and "358" in t and "1 EUR = 55.00" in t


def test_any_currency_product_switching_currency_is_baseline_not_change(cfg, tmp_path):
    prods = {"driffle": Product("driffle", "Driffle", "https://example.test/d", "ANY", lambda: None)}
    db = DB(str(tmp_path / "a.db"))
    e = Engine(cfg, db, prods, Outbox(db))
    fxmod.save(db, fxmod.Rate(Decimal("50"), "t", T0, T0, Decimal("55")))
    feed(e, "driffle", "6.03", cur="EUR")
    feed(e, "driffle", "300", cur="EGP", now=T0 + 1)
    assert msgs(e, "change") == [] and e.state("driffle")["currency"] == "EGP"
    feed(e, "driffle", "290", cur="EGP", now=T0 + 2)
    assert len(msgs(e, "change")) == 1


def test_driffle_eur_price_shown_with_egp_equivalent(eng):
    feed(eng, "driffle", "6.03")
    assert "6.03 EUR" in eng.prices_text(T0) and "332" in eng.prices_text(T0)   # 6.03*55


def test_note_is_stored_and_shown_under_the_table(eng):
    from aipro.fetchers import PriceResult
    eng.record_success("driffle", PriceResult(Decimal("6.03"), "EUR", "base", "أرخص عرض"), T0)
    assert "ℹ️ Driffle: أرخص عرض" in eng.prices_text(T0)
