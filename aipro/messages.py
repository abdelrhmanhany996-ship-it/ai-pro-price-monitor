"""Arabic message builders (HTML parse mode). Pure functions over plain data."""
from datetime import datetime
from decimal import Decimal
from html import escape
from zoneinfo import ZoneInfo

from .money import fmt_amount

PAUSE_BANNER = "⏸ <b>المراقبة متوقفة مؤقتًا</b> (/resume للاستئناف)\n"


def when(ts: int | None, tz: str) -> str:
    return datetime.fromtimestamp(ts, ZoneInfo(tz)).strftime("%Y-%m-%d %H:%M") if ts else "—"


def to_egp(price: Decimal, currency: str, fx) -> Decimal | None:
    if currency == "EGP":
        return price
    if currency == "USD" and fx is not None:
        return price * fx.rate
    return None


def price_line(product, st, fx, tz: str) -> str:
    """One product line for tables/status. Never invents a value."""
    name = escape(product.name)
    if st is None or st["price"] is None:
        return f"• <b>{name}</b>: غير متاح — لا توجد قراءة ناجحة بعد"
    price = Decimal(st["price"])
    line = f"• <b>{name}</b>: {fmt_amount(price, st['currency'])}"
    if st["currency"] == "USD":
        egp = to_egp(price, "USD", fx)
        line += f" ≈ {fmt_amount(egp, 'EGP')} (تقريبي)" if egp is not None else " (المقابل بالجنيه غير متاح حاليًا)"
    line += f"\n   آخر تحديث ناجح: {when(st['last_ok_ts'], tz)}"
    if st["status"] != "ok" and st["last_error"]:
        label = "تحتاج مراجعة" if st["status"] == "review" else "فشل الفحص"
        line += f"\n   ⚠️ {label}: {escape(st['last_error'])} — السعر أعلاه هو آخر سعر معروف"
    return line


def fx_footer(fx, tz: str) -> str:
    if fx is None:
        return "سعر الصرف: غير متاح حاليًا (تعذّر التحويل إلى الجنيه)"
    return (f"سعر الصرف المستخدم: 1 USD = {fx.rate:.4f} EGP ({fx.source}، "
            f"تحديث المصدر: {when(fx.source_ts or fx.fetched_ts, tz)})")


def prices_table(products, states, fx, tz: str) -> str:
    lines = [price_line(p, states.get(p.id), fx, tz) for p in products]
    return "\n".join(lines) + "\n" + fx_footer(fx, tz)


def change_report(product, old, new, cur, fx, ts, products, states, tz) -> str:
    diff, pct = new - old, (new - old) / old * 100
    word = "ارتفاع" if diff > 0 else "انخفاض"
    out = [f"📊 <b>تقرير تغيّر الأسعار</b>",
           f"المنتج: <b>{escape(product.name)}</b>",
           f"السعر السابق: {fmt_amount(old, cur)}",
           f"السعر الجديد: {fmt_amount(new, cur)}",
           f"التغير: {word} {fmt_amount(abs(diff), cur)}",
           f"نسبة التغير: {pct:+.2f}%"]
    if cur == "USD":
        o, n = to_egp(old, cur, fx), to_egp(new, cur, fx)
        out.append(f"المقابل التقريبي بالجنيه: {fmt_amount(n, 'EGP')} (كان {fmt_amount(o, 'EGP')})"
                   if fx else "المقابل التقريبي بالجنيه: غير متاح حاليًا")
    out += ["", "<b>آخر الأسعار:</b>", prices_table(products, states, fx, tz), "",
            f"وقت اكتشاف التغيير: {when(ts, tz)}"]
    return "\n".join(out)


def alert_text(product, price, cur, egp, threshold, fx, ts, link, tz, reminder_n=0) -> str:
    head = "🚨 <b>فرصة سعرية جديدة!</b>" if not reminder_n else f"⏰ <b>تذكير #{reminder_n}: السعر ما زال أقل من الحد</b>"
    out = [head, f"الموقع: <b>{escape(product.name)}</b>", f"السعر الحالي: {fmt_amount(price, cur)}"]
    if cur != "EGP":
        out.append(f"المقابل التقريبي بالجنيه: {fmt_amount(egp, 'EGP')}")
        out.append(fx_footer(fx, tz))
    out += [f"الحد المستهدف: أقل من {fmt_amount(threshold, 'EGP')}"]
    if cur == "EGP":
        pass
    out += [f'<a href="{escape(link, quote=True)}">افتح المنتج</a>',
            f"وقت اكتشاف السعر: {when(ts, tz)}"]
    return "\n".join(out)


def error_text(product, st, tz: str) -> str:
    last = (f"آخر سعر معروف: {fmt_amount(Decimal(st['price']), st['currency'])} "
            f"(تحديث: {when(st['last_ok_ts'], tz)})") if st["price"] else "لا يوجد سعر معروف سابق"
    return "\n".join([f"⚠️ <b>تعذّر فحص {escape(product.name)}</b>",
                      f"السبب: {escape(st['last_error'] or '—')}",
                      f"عدد الفحوصات الفاشلة المتتالية: {st['consecutive_failures']}",
                      last, "لن تُرسل تنبيهات سعر لهذا المنتج حتى ينجح الفحص."])


def recovered_text(product, st, tz: str) -> str:
    return f"✅ عاد فحص <b>{escape(product.name)}</b> للعمل. السعر الحالي: {fmt_amount(Decimal(st['price']), st['currency'])}"
