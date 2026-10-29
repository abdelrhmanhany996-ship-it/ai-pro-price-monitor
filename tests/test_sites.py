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


def test_maads_falls_back_to_other_host_on_network_error(monkeypatch):
    calls = []

    def fake(url, *a, **k):
        calls.append(url)
        if len(calls) == 1:
            raise FetchError("network", "URLError: x")
        return ld(199)
    monkeypatch.setattr(maads, "http_get", fake)
    assert str(maads.fetch().price) == "199" and calls == [maads.URL, maads.FALLBACK_URL]


def test_http_get_retries_transient_errors(monkeypatch):
    from aipro import fetchers
    n = {"c": 0}

    def flaky(url, timeout):
        n["c"] += 1
        if n["c"] < 3:
            raise FetchError("network", "URLError")
        return "ok"
    monkeypatch.setattr(fetchers, "_get", flaky)
    monkeypatch.setattr(fetchers.time, "sleep", lambda s: None)
    assert fetchers.http_get("u") == "ok" and n["c"] == 3
    n["c"] = -10                                       # blocked errors are not retried
    monkeypatch.setattr(fetchers, "_get", lambda u, t: (_ for _ in ()).throw(FetchError("blocked", "403")))
    with pytest.raises(FetchError):
        fetchers.http_get("u")


def _next(products, cur="EUR"):
    import json
    return ('<script id="__NEXT_DATA__" type="application/json">' +
            json.dumps({"props": {"pageProps": {"currency": cur, "items": products}}}) + "</script>")


def test_driffle_store_picks_cheapest_matching_listing():
    html = _next([{"title": "Google AI Pro - Gemini 18 Months (Global) - Activation Link", "price": 9.5},
                  {"title": "Google AI Pro - Gemini 18 Months (Global) - Activation Link", "price": 8.25},
                  {"title": "Google AI Pro - Gemini 3 Months", "price": 1.1}, {"title": "Other game", "price": 0.5}])
    r = driffle.parse_store(html)
    assert (str(r.price), r.currency) == ("8.25", "EUR")


def test_driffle_store_no_match_or_unknown_currency_not_guessed():
    with pytest.raises(FetchError):
        driffle.parse_store(_next([{"title": "Other", "price": 3}]))
    with pytest.raises(FetchError) as e:
        driffle.parse_store(_next([{"title": "Google AI Pro 18 Months", "price": 3}], cur="BRL"))
    assert e.value.kind == "currency"


def test_driffle_zero_price_product_page_falls_back_to_store(monkeypatch):
    zero = ld(0, "EUR")
    store = _next([{"title": "Google AI Pro - Gemini 18 Months", "price": 7.77}])
    monkeypatch.setattr(driffle, "http_get", lambda url, *a, **k: zero if "p9998937" in url else store)
    r = driffle.fetch()
    assert (str(r.price), r.currency) == ("7.77", "EUR")
