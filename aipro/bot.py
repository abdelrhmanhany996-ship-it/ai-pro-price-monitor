"""Telegram command handling. Pure: returns reply text, so it is testable without network."""
import logging

log = logging.getLogger("aipro.bot")

HELP = ("🤖 <b>أوامر البوت</b>\n"
        "/status — حالة النظام والأسعار والتنبيهات\n"
        "/prices — الأسعار الحالية المعروفة\n"
        "/pause — إيقاف الفحص والتنبيهات مؤقتًا\n"
        "/resume — استئناف الفحص والتنبيهات\n"
        "/help — هذه القائمة")
START = ("👋 أهلًا! أراقب أسعار Google AI Pro (18 شهر) على MAADS وZ2U وDriffle، "
         "وأرسل تنبيهًا عند نزول السعر عن الحد المستهدف وتقريرًا عند أي تغيّر.\n\n" + HELP)


def is_authorized(chat_id, configured: str) -> bool:
    return bool(configured) and str(chat_id) == str(configured)


def handle_command(engine, text: str, now: int, on_resume=None) -> str | None:
    cmd = text.strip().split()[0].split("@")[0].lower() if text.strip() else ""
    if cmd == "/start":
        return START
    if cmd == "/help":
        return HELP
    if cmd == "/status":
        return engine.status_text(now)
    if cmd == "/prices":
        return engine.prices_text(now)
    if cmd == "/pause":
        engine.set_paused(True, now)
        return "⏸ تم إيقاف الفحص والتنبيهات مؤقتًا. البيانات المحفوظة لم تُمسّ. /resume للاستئناف."
    if cmd == "/resume":
        engine.set_paused(False, now)
        if on_resume:
            on_resume()
        return "▶️ تم الاستئناف. جارٍ فحص الأسعار الآن قبل إصدار أي تنبيه جديد."
    return "أمر غير معروف. أرسل /help"
