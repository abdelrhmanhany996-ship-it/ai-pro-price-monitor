"""Telegram command handling. Pure: returns reply text, so it is testable without network."""
import logging

log = logging.getLogger("aipro.bot")

COMMANDS = [("prices", "💰 الأسعار الحالية"), ("status", "🖥 حالة النظام"),
            ("besttime", "⏰ أرخص وقت في اليوم"), ("pause", "⏸ إيقاف مؤقت"),
            ("resume", "▶️ استئناف"), ("help", "❓ المساعدة")]
# Persistent reply-keyboard buttons (shown when the user taps the message box)
KEYBOARD = [["💰 الأسعار", "🖥 الحالة"], ["⏰ أرخص وقت", "❓ مساعدة"], ["⏸ إيقاف", "▶️ استئناف"]]
LABELS = {"💰 الأسعار": "/prices", "🖥 الحالة": "/status", "⏰ أرخص وقت": "/besttime",
          "❓ مساعدة": "/help", "⏸ إيقاف": "/pause", "▶️ استئناف": "/resume"}

HELP = ("🤖 <b>أوامر البوت</b>\n"
        "الأسعار الحالية: /prices\n"
        "حالة النظام والتنبيهات: /status\n"
        "أرخص وقت في اليوم: /besttime\n"
        "إيقاف الفحص والتنبيهات مؤقتًا: /pause\n"
        "استئناف الفحص والتنبيهات: /resume\n"
        "هذه القائمة: /help\n\n"
        "أو اضغط الأزرار أسفل الشاشة 👇")
START = ("👋 أهلًا! أراقب أسعار Google AI Pro (18 شهر) على MAADS وZ2U وDriffle، "
         "وأرسل تنبيهًا عند نزول السعر عن الحد المستهدف وتقريرًا عند أي تغيّر.\n\n" + HELP)


def is_authorized(chat_id, configured: str) -> bool:
    return bool(configured) and str(chat_id) == str(configured)


def is_command_text(text: str) -> bool:
    t = (text or "").strip()
    return t.startswith("/") or t in LABELS


def handle_command(engine, text: str, now: int, on_resume=None) -> str | None:
    text = LABELS.get(text.strip(), text)
    cmd = text.strip().split()[0].split("@")[0].lower() if text.strip() else ""
    if cmd == "/start":
        return START
    if cmd == "/help":
        return HELP
    if cmd == "/status":
        return engine.status_text(now)
    if cmd == "/prices":
        return engine.prices_text(now)
    if cmd in ("/besttime", "/best"):
        return engine.best_times_text(now)
    if cmd == "/pause":
        engine.set_paused(True, now)
        return "⏸ تم إيقاف الفحص والتنبيهات مؤقتًا. البيانات المحفوظة لم تُمسّ. /resume للاستئناف."
    if cmd == "/resume":
        engine.set_paused(False, now)
        if on_resume:
            on_resume()
        return "▶️ تم الاستئناف. جارٍ فحص الأسعار الآن قبل إصدار أي تنبيه جديد."
    return "أمر غير معروف. أرسل /help"
