"""Parsers run on synthetic HTML that copies each site's real markup shape with FAKE prices."""
import pytest

from aipro.fetchers import FetchError
from aipro.sites import driffle, maads, z2u


def ld(price, cur="EGP", low=None):
    return ('<html><script type="application/ld+json">{"@type":"Product","offers":{"@type":"AggregateOffer",'
            f'"priceCurrency":"{cur}","lowPrice":{low or price},"highPrice":{price}}}}}</script></html>')


def z2u_html(price="7.77", unit="7.77", cur="USD"):
    return (f"<div class=\"priceItem\"> $ <span class='mbprice'>{price}</span> "
            f"<small class=\"fromSmallText hidden\">1 = {cur} $<span class=\"ut_price\">{unit}</span></small>"
            " Excludes payment processing fees</div>")


def test_maads_egp():
    r = maads.parse(ld(199))
    assert (str(r.price), r.currency) == ("199", "EGP")


def test_maads_wrong_currency_needs_review():
    with pytest.raises(FetchError) as e:
        maads.parse(ld(5, "USD"))
    assert e.value.kind == "currency"


def test_maads_missing_or_ambiguous_price():
    for html in ("<html></html>", ld(200, low=150)):
        with pytest.raises(FetchError) as e:
            maads.parse(html)
        assert e.value.kind == "parse"


def test_z2u_usd():
    r = z2u.parse(z2u_html())
    assert (str(r.price), r.currency) == ("7.77", "USD")
    assert "رسوم" in r.note


@pytest.mark.parametrize("html", ["<html></html>", z2u_html("7.77", "8.88"), z2u_html(cur="EUR")])
def test_z2u_unreadable_or_inconsistent(html):
    with pytest.raises(FetchError):
        z2u.parse(html)


def test_driffle_block_page_is_blocked_not_zero():
    with pytest.raises(FetchError) as e:
        driffle.parse("<html><head><title>Blocked - Driffle</title></head></html>")
    assert e.value.kind == "blocked"


def test_driffle_cheapest_offer_any_supported_currency():
    r = driffle.parse(ld(7.68, "EUR", low=6.48))
    assert (str(r.price), r.currency) == ("6.48", "EUR")
    assert driffle.parse(ld(5, "USD")).currency == "USD"


def test_driffle_unsupported_currency_needs_review():
    with pytest.raises(FetchError) as e:
        driffle.parse(ld(188, "BRL"))
    assert e.value.kind == "currency"


def test_driffle_takes_cheapest_across_blocks():
    def blk(p):
        return ('<script type="application/ld+json">{"@type":"Product","offers":'
                f'{{"priceCurrency":"EUR","price":{p}}}}}</script>')
    assert str(driffle.parse(blk(6.55) + blk(6.03) + blk(6.48)).price) == "6.03"


def test_driffle_mixed_currencies_not_guessed():
    mix = ('<script type="application/ld+json">{"@type":"Product","offers":{"priceCurrency":"EUR","price":6}}</script>'
           '<script type="application/ld+json">{"@type":"Product","offers":{"priceCurrency":"USD","price":7}}</script>')
    with pytest.raises(FetchError):
        driffle.parse(mix)
