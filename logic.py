"""Логика бота без сети: команды, кнопки, запись на разбор, вопросы к нейросети."""
import json
import re
import sys
from typing import Callable, Optional

import knowledge as k
from leads import save_lead

CMD_START, CMD_INCLUDES, CMD_PRICE, CMD_LEAD = "start", "includes", "price", "lead"
CMD_HELP, CMD_CANCEL, CMD_AGREE = "help", "cancel", "agree"

TEXT_TO_CMD = {
    "/start": CMD_START, "start": CMD_START, "начать": CMD_START, "привет": CMD_START,
    "/цена": CMD_PRICE, "цена": CMD_PRICE,
    "что входит": CMD_INCLUDES, "/входит": CMD_INCLUDES,
    "/запись": CMD_LEAD, "запись": CMD_LEAD, "хочу разбор": CMD_LEAD,
    "/помощь": CMD_HELP, "помощь": CMD_HELP, "/help": CMD_HELP,
    "/отмена": CMD_CANCEL, "отмена": CMD_CANCEL,
    "согласен(а)": CMD_AGREE,
}

MAX_QUESTION = 500
HISTORY_TURNS = 3


def _button(label: str, cmd: str, color: str = "secondary") -> dict:
    return {
        "action": {"type": "text", "label": label, "payload": json.dumps({"cmd": cmd})},
        "color": color,
    }


def main_keyboard() -> str:
    return json.dumps({
        "one_time": False,
        "buttons": [
            [_button("Что входит", CMD_INCLUDES), _button("Цена", CMD_PRICE)],
            [_button("Хочу разбор", CMD_LEAD, "primary")],
        ],
    }, ensure_ascii=False)


def consent_keyboard() -> str:
    return json.dumps({
        "one_time": True,
        "buttons": [[_button("Согласен(а)", CMD_AGREE, "positive"), _button("Отмена", CMD_CANCEL, "negative")]],
    }, ensure_ascii=False)


VK_MENTION = re.compile(r"\[(?:id|club|public)\d+\|([^\]]*)\]")
EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
TG_LINK = re.compile(r"(?:https?://)?t\.me/[A-Za-z0-9_]{3,32}")
TG_HANDLE = re.compile(r"(?<!\w)@[A-Za-z0-9_]{3,32}(?!\w)")  # \w ловит и русские буквы: «@Evgеnia» с русской «е» не обрежется до «@Evg»


def extract_contact(text: str) -> Optional[str]:
    """Достаёт контакт (почта, ссылка t.me или @ник) из сообщения.

    ВКонтакте превращает «@имя» в своё упоминание: «[id123|@имя]» или «@имя (Имя Фамилия)».
    Поэтому сначала снимаем разметку упоминания, потом ищем контакт в тексте."""
    text = VK_MENTION.sub(r"\1", text or "").strip()
    for pattern in (EMAIL, TG_LINK, TG_HANDLE):
        m = pattern.search(text)
        if m:
            return m.group(0)
    return None


def clean_markdown(text: str) -> str:
    """ВКонтакте не отображает Markdown, поэтому убираем разметку из ответов нейросети."""
    text = re.sub(r"```[a-zA-Z]*\n?", "", text)                      # блоки кода
    text = text.replace("`", "")                                        # инлайн-код
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text, flags=re.S)           # **жирный**
    text = re.sub(r"__(.+?)__", r"\1", text, flags=re.S)               # __жирный__
    text = re.sub(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])", r"\1", text)  # *курсив*
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.M)         # заголовки
    text = re.sub(r"^(\s*)[*+]\s+", r"\1- ", text, flags=re.M)        # маркеры списка
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r"\1 (\2)", text)  # [текст](ссылка)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def looks_like_contact(text: str) -> bool:
    return extract_contact(text) is not None


class Bot:
    """Один объект на весь бот. Состояние хранится в памяти процесса."""

    def __init__(self, leads_path: str, llm: Optional[Callable[[list], str]] = None,
                 on_lead: Optional[Callable[[str], None]] = None, system_prompt: Optional[str] = None):
        self.system_prompt = system_prompt or k.SYSTEM_PROMPT
        self.leads_path = leads_path
        self.llm = llm
        self.on_lead = on_lead
        self.state: dict = {}
        self.history: dict = {}

    def handle(self, user_id: int, text: str, payload_cmd: Optional[str] = None,
               first_name: str = "") -> list:
        """Возвращает список ответов: [(текст, клавиатура или None), ...]."""
        text = (text or "").strip()
        cmd = payload_cmd or TEXT_TO_CMD.get(text.lower())

        if cmd == CMD_CANCEL:
            self.state.pop(user_id, None)
            return [(k.LEAD_CANCELLED, main_keyboard())]

        if user_id in self.state:
            return self._lead_step(user_id, text, cmd)

        if cmd == CMD_START:
            name = first_name or "добрый день"
            return [(k.GREETING.format(name=name, bot_name=k.BOT_NAME), main_keyboard())]
        if cmd == CMD_INCLUDES:
            return [(k.INCLUDES, main_keyboard())]
        if cmd == CMD_PRICE:
            return [(k.PRICE, main_keyboard())]
        if cmd == CMD_HELP:
            return [(k.HELP, main_keyboard())]
        if cmd == CMD_LEAD:
            self.state[user_id] = {"step": "name", "vk_name": first_name}
            return [(k.ASK_NAME, None)]
        if not text:
            return [(k.HELP, main_keyboard())]
        return [(self._ask_llm(user_id, text), main_keyboard())]

    def _lead_step(self, user_id: int, text: str, cmd: Optional[str]) -> list:
        st = self.state[user_id]
        if st["step"] == "name":
            if not text or len(text) > 80 or cmd:
                return [(k.ASK_NAME, None)]
            st["name"], st["step"] = text, "contact"
            return [(k.ASK_CONTACT.format(name=text), None)]
        if st["step"] == "contact":
            contact = extract_contact(text)
            if not contact:
                print(f"Контакт не распознан, текст от ВК: {text!r}", file=sys.stderr)
                return [(k.BAD_CONTACT, None)]
            st["contact"], st["step"] = contact, "consent"
            return [(k.ASK_CONSENT.format(name=st["name"], contact=contact), consent_keyboard())]
        if st["step"] == "consent":
            if cmd != CMD_AGREE:
                return [(k.USE_BUTTONS, consent_keyboard())]
            name, contact = st["name"], st["contact"]
            save_lead(self.leads_path, user_id, name, contact)
            self.state.pop(user_id, None)
            if self.on_lead:
                self.on_lead(f"Новая заявка из VK: {name}, {contact} (vk.com/id{user_id})")
            return [(k.LEAD_SAVED.format(name=name, contact=contact), main_keyboard())]
        self.state.pop(user_id, None)
        return [(k.HELP, main_keyboard())]

    def _ask_llm(self, user_id: int, text: str) -> str:
        if self.llm is None:
            return k.NO_LLM
        question = text[:MAX_QUESTION]
        hist = self.history.setdefault(user_id, [])
        messages = [{"role": "system", "content": self.system_prompt}] + hist + [{"role": "user", "content": question}]
        try:
            answer = (self.llm(messages) or "").strip()
        except Exception as e:
            print(f"Ошибка нейросети: {e}", file=sys.stderr)
            return k.LLM_UNAVAILABLE
        if not answer:
            print("Ошибка нейросети: пустой ответ модели", file=sys.stderr)
            return k.LLM_UNAVAILABLE
        answer = clean_markdown(answer) or k.LLM_UNAVAILABLE
        hist += [{"role": "user", "content": question}, {"role": "assistant", "content": answer}]
        del hist[:-2 * HISTORY_TURNS]
        return answer
