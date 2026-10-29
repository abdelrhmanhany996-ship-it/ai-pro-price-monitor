"""Arabic message builders (HTML parse mode). Prices are shown as compact monospace tables."""
from datetime import datetime
from decimal import Decimal
from html import escape
from zoneinfo import ZoneInfo

from .money import fmt_amount

LRM = "‎"
PAUSE_BANNER = "⏸ <b>المراقبة متوقفة مؤقتًا</b> — /resume للاستئناف\n"


def when(ts: int | None, tz: str, short: bool = False) -> str:
    if not ts:
        return "—"
    dt = datetime.fromtimestamp(ts, ZoneInfo(tz))
    if short:
        return dt.strftime("%H:%M") if dt.date() == datetime.now(ZoneInfo(tz)).date() else dt.strftime("%m-%d %H:%M")
    return dt.strftime("%Y-%m-%d %H:%M")


def to_egp(price: Decimal, currency: str, fx) -> Decimal | None:
    if currency == "EGP":
        return price
    if currency == "USD" and fx is not None:
        return price * fx.rate
    if currency == "EUR" and fx is not None and fx.eur:
        return price * fx.eur
    return None


def fx_footer(fx, tz: str) -> str:
    if fx is None:
        return "💱 سعر الصرف غير متاح حاليًا"
    eur = f"  {LRM}1 EUR = {fx.eur:.2f}" if fx.eur else ""
    return f"💱 {LRM}1 USD = {fx.rate:.2f}{eur} EGP{LRM} · {when(fx.source_ts or fx.fetched_ts, tz, True)}"


def _table(headers, rows, marks=None) -> str:
    """Monospace table (Latin text only, so columns stay aligned). marks = one emoji per row."""
    widths = [max(len(str(c)) for c in col) for col in zip(headers, *rows)]
    fmt = lambda r: "  ".join(str(c).ljust(w) for c, w in zip(r, widths)).rstrip()  # noqa: E731
    lines = [("   " if marks else "") + fmt(headers)]
    for i, r in enumerate(rows):
        lines.append((f"{marks[i]} " if marks else "") + fmt(r))
    return "<pre>" + escape("\n".join(lines)) + "</pre>"


def _row_state(product, st, fx, threshold: Decimal):
    """(mark, price_text, egp_text, updated_text) — never invents a value."""
    if st is None or st["price"] is None:
        return "🔴", "—", "—", "—"
    price = Decimal(st["price"])
    egp = to_egp(price, st["currency"], fx)
    mark = "🔴" if st["status"] != "ok" else ("🟢" if egp is not None and egp < threshold else "⚪")
    return mark, fmt_amount(price, st["currency"]), f"{egp:,.0f}" if egp is not None else "n/a", ""


def prices_table(products, states, fx, tz: str, threshold: Decimal = Decimal("200")) -> str:
    rows, marks, problems = [], [], False
    for p in products:
        st = states.get(p.id)
        mark, price, egp, _ = _row_state(p, st, fx, threshold)
        upd = when(st["last_ok_ts"], tz, True) if st is not None and st["price"] is not None else "—"
        rows.append([p.name, price, egp, upd])
        marks.append(mark)
        problems |= mark == "🔴"
    out = _table(["Site", "Price", "EGP", "Updated"], rows, marks)
    legend = f"🟢 أقل من {threshold:f} جنيه · ⚪ عادي" + (" · 🔴 فشل الفحص/لا بيانات (آخر سعر معروف)" if problems else "")
    notes = [f"{p.name}: {states[p.id]['note']}" for p in products
             if states.get(p.id) is not None and states[p.id]["price"] is not None and states[p.id]["note"]]
    note_line = ("ℹ️ " + " · ".join(notes) + "\n") if notes else ""
    return f"{out}\n{legend}\n{note_line}{fx_footer(fx, tz)}"


def change_report(product, old, new, cur, fx, ts, products, states, tz, threshold=Decimal("200")) -> str:
    diff, pct = new - old, (new - old) / old * 100
    arrow = "🔺" if diff > 0 else "🔻"
    rows = [["Was", fmt_amount(old, cur), _egp_txt(old, cur, fx)],
            ["Now", fmt_amount(new, cur), _egp_txt(new, cur, fx)],
            ["Diff", f"{diff:+.2f} {cur}", f"{pct:+.2f}%"]]
    return "\n".join([f"{arrow} <b>تغيّر سعر {escape(product.name)}</b>",
                      _table(["", "Price", "EGP / %"], rows), "",
                      prices_table(products, states, fx, tz, threshold), f"🕒 {when(ts, tz)}"])


def _egp_txt(price, cur, fx) -> str:
    e = to_egp(price, cur, fx)
    return f"{e:,.0f}" if e is not None else "n/a"


def alert_text(product, price, cur, egp, threshold, fx, ts, link, tz, reminder_n=0) -> str:
    head = ("🚨 <b>فرصة سعرية جديدة!</b>" if not reminder_n
            else f"⏰ <b>تذكير #{reminder_n} — السعر ما زال أقل من الحد</b>")
    line = fmt_amount(price, cur) + (f"  ≈  {egp:,.0f} EGP" if cur != "EGP" else "")
    parts = [head, f"<b>{escape(product.name)}</b>", f"<pre>{escape(line)}</pre>",
             f"الحد: أقل من {threshold:f} جنيه"]
    if cur != "EGP":
        parts.append(fx_footer(fx, tz))
    parts += [f'🔗 <a href="{escape(link, quote=True)}">افتح المنتج</a>', f"🕒 {when(ts, tz)}"]
    return "\n".join(parts)


def error_text(product, st, tz: str) -> str:
    last = (f"آخر سعر معروف: {fmt_amount(Decimal(st['price']), st['currency'])} ({when(st['last_ok_ts'], tz, True)})"
            if st["price"] else "لا يوجد سعر معروف سابق")
    return "\n".join([f"⚠️ <b>تعذّر فحص {escape(product.name)}</b>",
                      f"السبب: {escape(st['last_error'] or '—')}",
                      f"فشل متتالٍ: {st['consecutive_failures']} · {last}",
                      "لا تنبيهات سعر لهذا المنتج حتى ينجح الفحص."])


def recovered_text(product, st, tz: str) -> str:
    return f"✅ عاد فحص <b>{escape(product.name)}</b> — {fmt_amount(Decimal(st['price']), st['currency'])}"


def daily_table(rows) -> str:
    """rows: [name, price, egp, min, max, changes, fails, mark]"""
    return _table(["Site", "Now", "EGP", "Min", "Max", "Chg", "Fail"], [r[:7] for r in rows], [r[7] for r in rows])
