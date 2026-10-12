"""Тексты бота и системный промпт нейросети. Факты проекта лежат в папке knowledge/."""
import os

LANDING_URL = "https://videootdel.evskakunova-ai.ru/"
CONSENT_URL = "https://evskakunova-ai.ru/legal/consent/"

BOT_NAME = "Ася"  # имя помощника: меняется здесь, в приветствии и в system_prompt.md подставится само
PROMPT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "system_prompt.md")


def load_system_prompt(path: str = PROMPT_FILE, bot_name: str = BOT_NAME) -> str:
    """Системный промпт хранится в файле system_prompt.md: правьте его, не трогая код."""
    with open(path, encoding="utf-8") as f:
        return f.read().strip().replace("{bot_name}", bot_name)


SYSTEM_PROMPT = load_system_prompt()

MATERIALS_LIMIT = 12000  # символов: больше в промпт не берём, чтобы не раздувать запрос


def load_materials(folder: str, limit: int = MATERIALS_LIMIT):
    """Читает файлы .md и .txt из папки знаний. Возвращает (текст, число файлов, обрезано ли)."""
    if not os.path.isdir(folder):
        return "", 0, False
    parts, total, count, truncated = [], 0, 0, False
    for name in sorted(os.listdir(folder)):
        if name.startswith(".") or not name.lower().endswith((".md", ".txt")):
            continue
        with open(os.path.join(folder, name), encoding="utf-8") as f:
            text = f.read().strip()
        if not text:
            continue
        if total + len(text) > limit:
            text, truncated = text[: max(0, limit - total)], True
        parts.append(f"### Файл {name}\n{text}")
        total += len(text)
        count += 1
        if truncated:
            break
    return "\n\n".join(parts), count, truncated


def build_system_prompt(folder: str):
    """Собирает итоговый системный промпт: правила + материалы из папки знаний."""
    materials, count, truncated = load_materials(folder)
    prompt = SYSTEM_PROMPT
    if materials:
        prompt += "\n\nМатериалы проекта:\n" + materials
    return prompt, count, truncated

GREETING = (
    "Здравствуйте, {name}! Я {bot_name}, помощник по гайду «Видео-отдел в Claude Code за один вечер». "
    "Могу рассказать, что входит и сколько стоит, ответить на вопросы или записать Вас на разбор. "
    "Выберите кнопку или просто напишите вопрос."
)

INCLUDES = (
    "В гайде:\n"
    "• 3 файла-агента: Расшифровщик, Оформитель, Сборщик\n"
    "• три готовых промпта под каждую роль\n"
    "• команда запуска одной строкой\n"
    "• чек-лист приёмки на 10 пунктов\n"
    "• 5 граблей и решения\n"
    "• PDF после оплаты"
)

PRICE = (
    "Самостоятельно: 1990 ₽ разово, без подписки.\n"
    "С сопровождением: 15 000 ₽ (закрытый чат в Телеграме, группа до 10 человек, месяц).\n"
    f"Подробности и оплата: {LANDING_URL}"
)

HELP = (
    "Команды:\n"
    "/start: приветствие и меню\n"
    "/цена: сколько стоит\n"
    "/запись: оставить заявку на разбор\n"
    "/отмена: прервать запись\n"
    "Любой другой вопрос можно просто написать."
)

ASK_NAME = "Как к Вам обращаться? Напишите имя. Чтобы прервать запись, отправьте /отмена."
ASK_CONTACT = "Спасибо, {name}. Оставьте контакт для связи: Telegram (@имя) или почту."
BAD_CONTACT = "Не похоже на контакт. Напишите Telegram (@имя) или почту, например name@mail.ru."
ASK_CONSENT = (
    "Проверьте: {name}, контакт {contact}.\n"
    "Нажимая «Согласен(а)», Вы даёте согласие на обработку персональных данных: "
    f"{CONSENT_URL}"
)
LEAD_SAVED = "Заявка принята, {name}. Евгения свяжется с Вами по контакту {contact}."
LEAD_CANCELLED = "Запись отменена. Если передумаете, нажмите «Хочу разбор» или отправьте /запись."
USE_BUTTONS = "Нажмите «Согласен(а)» или «Отмена»."

LLM_UNAVAILABLE = (
    "Сейчас не получается ответить на этот вопрос. Посмотрите «Что входит» и «Цена» "
    "или оставьте заявку командой /запись, Евгения ответит лично."
)
NO_LLM = (
    "На такие вопросы я отвечаю с помощью нейросети, но она пока не подключена. "
    "Нажмите «Что входит» или «Цена» либо оставьте заявку командой /запись."
)
