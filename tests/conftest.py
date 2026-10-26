import sys
import time
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aipro import fx as fxmod  # noqa: E402
from aipro.config import Settings  # noqa: E402
from aipro.db import DB  # noqa: E402
from aipro.engine import Engine  # noqa: E402
from aipro.fetchers import PriceResult  # noqa: E402
from aipro.outbox import Outbox  # noqa: E402
from aipro.products import Product  # noqa: E402

T0 = 1_800_000_000  # fixed fake "now"; all prices in tests are FAKE


def make_products():
    dummy = lambda: None  # noqa: E731
    return {p.id: p for p in (
        Product("maads", "MAADS", "https://example.test/maads", "EGP", dummy),
        Product("z2u", "Z2U", "https://example.test/z2u", "USD", dummy),
        Product("driffle", "Driffle", "https://example.test/driffle", "EGP", dummy),
    )}


@pytest.fixture
def cfg():
    return Settings(chat_id="42", token="t", confirm_checks=1, reminder_interval=600, error_alert_after=3, track_base_url="https://trk.test")


@pytest.fixture
def env(cfg, tmp_path):
    db = DB(str(tmp_path / "t.db"))
    ob = Outbox(db)
    eng = Engine(cfg, db, make_products(), ob)
    fxmod.save(db, fxmod.Rate(Decimal("50"), "test-fx", T0, T0))
    return eng


def feed(eng, pid, price, cur=None, now=T0):
    cur = cur or eng.products[pid].currency
    eng.record_success(pid, PriceResult(Decimal(str(price)), cur), now)


def msgs(eng, kind=None):
    q = "SELECT * FROM messages" + (" WHERE kind=?" if kind else "") + " ORDER BY id"
    return eng.db.q(q, (kind,) if kind else ())
