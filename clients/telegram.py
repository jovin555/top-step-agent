import requests


class TelegramClient:
    _BASE = "https://api.telegram.org/bot{token}/{method}"

    def __init__(self, token: str, chat_id: str):
        self.token   = token
        self.chat_id = chat_id

    def send_message(self, text: str, parse_mode: str = "Markdown") -> bool:
        url = self._BASE.format(token=self.token, method="sendMessage")
        payload = {
            "chat_id":                  self.chat_id,
            "text":                     text,
            "parse_mode":               parse_mode,
            "disable_web_page_preview": True,
        }
        try:
            resp = requests.post(url, json=payload, timeout=15)
            if not resp.ok:
                print(f"  Telegram error {resp.status_code}: {resp.text[:200]}")
            return resp.ok
        except requests.RequestException as e:
            print(f"  Telegram request failed: {e}")
            return False
