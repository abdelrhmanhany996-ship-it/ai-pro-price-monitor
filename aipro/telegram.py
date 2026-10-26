import json
import urllib.error
import urllib.request


class TelegramError(Exception):
    def __init__(self, message: str, permanent: bool = False):
        super().__init__(message)
        self.permanent = permanent


class Telegram:
    def __init__(self, token: str, chat_id: str, base: str = "https://api.telegram.org"):
        self.token, self.chat_id, self.base = token, str(chat_id), base

    def call(self, method: str, payload: dict, timeout: int = 20):
        req = urllib.request.Request(
            f"{self.base}/bot{self.token}/{method}",
            json.dumps(payload).encode(), {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.load(r)
        except urllib.error.HTTPError as e:   # never include e.url: it contains the token
            try:
                desc = json.load(e).get("description", "")
            except Exception:
                desc = ""
            raise TelegramError(f"{method}: HTTP {e.code} {desc}",
                                permanent=e.code in (400, 403) and "chat not found" not in desc.lower()
                                and e.code != 429) from None
        except Exception as e:
            raise TelegramError(f"{method}: {type(e).__name__}") from None
        if not data.get("ok"):
            raise TelegramError(f"{method}: {data.get('description')}")
        return data["result"]

    def send(self, text: str, buttons=None, chat_id: str | None = None) -> None:
        p = {"chat_id": chat_id or self.chat_id, "text": text[:4096], "parse_mode": "HTML",
             "disable_web_page_preview": True}
        if buttons:
            p["reply_markup"] = {"inline_keyboard": buttons}
        self.call("sendMessage", p)

    def get_me(self) -> dict:
        return self.call("getMe", {})

    def updates(self, offset: int | None, wait: int = 25) -> list:
        p = {"timeout": wait, "allowed_updates": ["message", "callback_query"]}
        if offset is not None:
            p["offset"] = offset
        return self.call("getUpdates", p, timeout=wait + 10)

    def answer_callback(self, cb_id: str, text: str) -> None:
        self.call("answerCallbackQuery", {"callback_query_id": cb_id, "text": text})
