"""VK AI-бот по гайду «Видео-отдел в Claude Code».

Запуск:
    python bot.py            боевой режим (нужны ключи ВК в .env)
    python bot.py --console  чат в терминале без ВКонтакте, для проверки логики
"""
import json
import os
import sys

import knowledge
from llm import make_llm
from logic import Bot

BASE = os.path.dirname(os.path.abspath(__file__))
LEADS_PATH = os.path.join(BASE, "data", "leads.csv")
KNOWLEDGE_DIR = os.path.join(BASE, "knowledge")


def load_env(path: str = os.path.join(BASE, ".env")) -> None:
    """Читает .env рядом с ботом. Значения попадают только в переменные процесса."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def build_llm():
    key = os.environ.get("LLM_API_KEY", "").strip()
    if not key:
        return None
    return make_llm(key, os.environ.get("LLM_BASE_URL", ""), os.environ.get("LLM_MODEL", ""))


def run_console(bot: Bot) -> None:
    print("Консольный режим. Команды: /start, /цена, /запись. Выход: Ctrl+C.\n")
    while True:
        try:
            text = input("Вы: ")
        except (EOFError, KeyboardInterrupt):
            print()
            return
        for reply, _kb in bot.handle(1, text, None, "Евгения"):
            print(f"Бот: {reply}\n")


def run_vk(bot_factory) -> None:
    from vk import VK, VKError

    token = os.environ.get("VK_GROUP_TOKEN", "").strip()
    group_id = os.environ.get("VK_GROUP_ID", "").strip()
    if not token or not group_id.isdigit():
        sys.exit("Заполните VK_GROUP_TOKEN и VK_GROUP_ID в файле .env (образец: .env.example).")
    vk = VK(token, int(group_id))
    admin = os.environ.get("ADMIN_VK_ID", "").strip()

    def notify(text: str) -> None:
        if admin.isdigit():
            try:
                vk.send(int(admin), text)
            except Exception as e:
                print("Не удалось уведомить администратора:", e)

    bot = bot_factory(on_lead=notify)
    try:
        vk.connect()
    except VKError as e:
        sys.exit(f"Не удалось подключиться к ВКонтакте: {e}\n" + VK_HINTS.get(e.code, "Проверьте ключ и ID сообщества."))
    print("Бот запущен. Остановить: Ctrl+C.")
    for msg in vk.events():
        user_id = msg.get("from_id")
        if not user_id or user_id < 0:
            continue
        payload = msg.get("payload")
        payload_cmd = None
        if payload:
            try:
                payload_cmd = json.loads(payload).get("cmd")
            except (ValueError, AttributeError):
                pass
        name = vk.first_name(user_id)
        vk.set_typing(user_id)
        try:
            for text, keyboard in bot.handle(user_id, msg.get("text", ""), payload_cmd, name):
                try:
                    vk.send(user_id, text, keyboard)
                except VKError as e:
                    if e.code != 912 or not keyboard:
                        raise
                    print("Кнопки не отправлены: включите «Возможности ботов» (Управление, Сообщения, Настройки для бота). "
                          "Отвечаю без кнопок.")
                    vk.send(user_id, text)
        except Exception as e:
            print("Ошибка обработки сообщения:", e)


VK_HINTS = {
    5: "Неверный ключ доступа. Проверьте VK_GROUP_TOKEN: без пробелов и кавычек.",
    15: ("Ключу не хватает прав. Создайте НОВЫЙ ключ с правами «управление сообществом» "
         "и «сообщения сообщества», вставьте его в VK_GROUP_TOKEN, старый ключ удалите."),
    100: "Проверьте VK_GROUP_ID: это число сообщества без минуса и без слова club.",
    27: "Это ключ пользователя, а нужен ключ сообщества (Управление → Работа с API).",
}


def check_env() -> None:
    """Показывает, какие переменные заполнены. Значения не печатаются."""
    for name in ("VK_GROUP_TOKEN", "VK_GROUP_ID", "LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL", "ADMIN_VK_ID"):
        value = os.environ.get(name, "")
        if not value:
            status = "ПУСТО"
        elif value != value.strip() or '"' in value or "'" in value or " " in value:
            status = "заполнено, но внутри пробел или кавычка: уберите"
        else:
            status = "заполнено"
        print(f"{name:16s} {status}")
    print("\nФайл .env:", "найден" if os.path.exists(os.path.join(BASE, ".env")) else "НЕ найден рядом с bot.py")

    token = os.environ.get("VK_GROUP_TOKEN", "").strip()
    gid = os.environ.get("VK_GROUP_ID", "").strip()
    if not token:
        return
    from vk import VK, VKError
    vk = VK(token, int(gid) if gid.isdigit() else 0)
    print("\nПроверка ключа во ВКонтакте:")
    try:
        resp = vk.call("groups.getById")
        groups = resp.get("groups", resp) if isinstance(resp, dict) else resp
        for g in groups:
            print(f"  сообщество ключа: «{g.get('name')}», ID {g.get('id')}",
                  "(совпадает с VK_GROUP_ID)" if str(g.get("id")) == gid else "(НЕ совпадает с VK_GROUP_ID!)")
    except VKError as e:
        print("  не удалось определить сообщество:", e)
    try:
        perms = vk.call("groups.getTokenPermissions")
        names = [p.get("name") for p in perms.get("permissions", [])]
        print("  права ключа:", ", ".join(n for n in names if n) or "не удалось прочитать")
    except VKError as e:
        print("  не удалось прочитать права:", e)
    try:
        lp = vk.call("groups.getLongPollSettings", group_id=int(gid))
        events = lp.get("events", {})
        print(f"  Long Poll: {'ВКЛЮЧЁН' if lp.get('is_enabled') else 'ВЫКЛЮЧЕН'}, версия API {lp.get('api_version')}")
        print(f"  событие «Входящее сообщение» (message_new): {'включено' if events.get('message_new') else 'ВЫКЛЮЧЕНО'}")
    except (VKError, ValueError) as e:
        print("  не удалось прочитать настройки Long Poll:", e)


def main() -> None:
    load_env()
    if "--check" in sys.argv:
        check_env()
        return
    llm = build_llm()
    prompt, files, truncated = knowledge.build_system_prompt(KNOWLEDGE_DIR)
    print("Нейросеть:", f"подключена ({llm.model})" if llm else "не подключена (нет LLM_API_KEY)")
    print(f"Знания о проекте: {files} файл(ов) из папки knowledge/" + (" (часть обрезана, лимит 12000 символов)" if truncated else ""))
    if "--console" in sys.argv:
        run_console(Bot(LEADS_PATH, llm, system_prompt=prompt))
    else:
        run_vk(lambda on_lead: Bot(LEADS_PATH, llm, on_lead, system_prompt=prompt))


if __name__ == "__main__":
    main()
