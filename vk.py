"""Минимальный клиент ВКонтакте: Bots Long Poll и отправка сообщений."""
import random
import time

import requests

API = "https://api.vk.com/method/"
API_VERSION = "5.199"
RECONNECT_DELAY = 5


class VKError(Exception):
    def __init__(self, message: str, code: int = 0):
        super().__init__(message)
        self.code = code


class VK:
    def __init__(self, token: str, group_id: int):
        self.token = token
        self.group_id = group_id
        self.server = self.key = self.ts = None

    def call(self, method: str, **params):
        params.update(access_token=self.token, v=API_VERSION)
        data = requests.post(API + method, data=params, timeout=30).json()
        if "error" in data:
            err = data["error"]
            raise VKError(f"{method}: {err.get('error_msg')} (код {err.get('error_code')})", err.get("error_code", 0))
        return data["response"]

    def first_name(self, user_id: int) -> str:
        try:
            return self.call("users.get", user_ids=user_id)[0].get("first_name", "")
        except Exception:
            return ""

    def set_typing(self, user_id: int) -> None:
        """Показывает «печатает…» в диалоге. Ошибки не важны: это только анимация."""
        try:
            self.call("messages.setActivity", user_id=user_id, peer_id=user_id, type="typing")
        except Exception:
            pass

    def send(self, user_id: int, text: str, keyboard: str = None) -> None:
        params = dict(user_id=user_id, random_id=random.randint(1, 2**31 - 1), message=text)
        if keyboard:
            params["keyboard"] = keyboard
        self.call("messages.send", **params)

    def connect(self) -> None:
        info = self.call("groups.getLongPollServer", group_id=self.group_id)
        self.server, self.key, self.ts = info["server"], info["key"], info["ts"]

    def events(self):
        """Бесконечно отдаёт события message_new. При обрыве связи сам переподключается."""
        while True:
            try:
                if not self.server:
                    self.connect()
                data = requests.get(
                    self.server,
                    params={"act": "a_check", "key": self.key, "ts": self.ts, "wait": 25},
                    timeout=40,
                ).json()
            except (requests.RequestException, ValueError, VKError) as e:
                print(f"Связь с ВК прервалась ({e.__class__.__name__}), повтор через {RECONNECT_DELAY} с.")
                self.server = None  # на следующем круге получим новый адрес Long Poll
                time.sleep(RECONNECT_DELAY)
                continue
            failed = data.get("failed")
            if failed == 1:
                self.ts = data["ts"]
                continue
            if failed in (2, 3):
                self.server = None
                continue
            self.ts = data.get("ts", self.ts)
            for update in data.get("updates", []):
                if update.get("type") == "message_new":
                    yield update["object"]["message"]
