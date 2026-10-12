"""Тесты логики бота без сети. Запуск: python -m unittest -v"""
import csv
import json
import os
import tempfile
import unittest

import knowledge as k
from leads import save_lead
from logic import Bot, clean_markdown, extract_contact, looks_like_contact, main_keyboard, consent_keyboard


class BotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "data", "leads.csv")
        self.notified = []
        self.bot = Bot(self.path, llm=None, on_lead=self.notified.append)

    def tearDown(self):
        self.tmp.cleanup()

    def say(self, text, payload=None, uid=1):
        return self.bot.handle(uid, text, payload, "Анна")

    def test_greeting_uses_profile_name(self):
        reply, kb = self.say("/start")[0]
        self.assertIn("Анна", reply)
        self.assertIsNotNone(kb)

    def test_price_has_both_tariffs_and_link(self):
        reply = self.say("Цена")[0][0]
        self.assertIn("1990", reply)
        self.assertIn("15 000", reply)
        self.assertIn(k.LANDING_URL, reply)

    def test_button_payload_works_like_text(self):
        self.assertEqual(self.say("что-то", payload="includes")[0][0], k.INCLUDES)

    def test_lead_happy_path_saves_csv_and_notifies(self):
        self.assertEqual(self.say("/запись")[0][0], k.ASK_NAME)
        self.assertIn("Мария", self.say("Мария")[0][0])
        reply, kb = self.say("@maria_test")[0]
        self.assertIn("Согласен", kb)
        self.assertIn(k.CONSENT_URL, reply)
        done = self.say("Согласен(а)", payload="agree")[0][0]
        self.assertIn("Мария", done)
        with open(self.path, encoding="utf-8") as f:
            rows = list(csv.reader(f))
        self.assertEqual(rows[0], ["datetime", "vk_id", "name", "contact"])
        self.assertEqual(rows[1][1:], ["1", "Мария", "@maria_test"])
        self.assertEqual(len(self.notified), 1)
        self.assertNotIn(1, self.bot.state)

    def test_bad_contact_reprompts_and_does_not_save(self):
        self.say("/запись"); self.say("Мария")
        self.assertEqual(self.say("просто текст")[0][0], k.BAD_CONTACT)
        self.assertFalse(os.path.exists(self.path))

    def test_cancel_at_any_step(self):
        self.say("/запись"); self.say("Мария")
        self.assertEqual(self.say("/отмена")[0][0], k.LEAD_CANCELLED)
        self.assertNotIn(1, self.bot.state)

    def test_no_consent_no_save(self):
        self.say("/запись"); self.say("Мария"); self.say("maria@mail.ru")
        self.assertEqual(self.say("не знаю")[0][0], k.USE_BUTTONS)
        self.assertFalse(os.path.exists(self.path))
        self.say("Отмена", payload="cancel")
        self.assertFalse(os.path.exists(self.path))

    def test_users_are_independent(self):
        self.say("/запись", uid=1)
        self.assertIn(1, self.bot.state)
        self.assertNotIn(2, self.bot.state)
        self.assertEqual(self.say("Цена", uid=2)[0][0], k.PRICE)

    def test_question_without_llm_gives_fallback(self):
        self.assertEqual(self.say("Подойдёт ли Windows?")[0][0], k.NO_LLM)

    def test_question_with_llm_uses_system_prompt_and_history(self):
        seen = []
        def fake_llm(messages):
            seen.append(messages)
            return "Подойдёт, нужен Claude Code."
        bot = Bot(self.path, llm=fake_llm)
        self.assertEqual(bot.handle(1, "Подойдёт Windows?", None, "Анна")[0][0], "Подойдёт, нужен Claude Code.")
        bot.handle(1, "А Mac?", None, "Анна")
        self.assertEqual(seen[0][0]["role"], "system")
        self.assertEqual(len(seen[1]), 4)  # system + прошлый вопрос и ответ + новый вопрос

    def test_llm_error_and_empty_answer_fall_back(self):
        def boom(_): raise RuntimeError("сеть")
        self.assertEqual(Bot(self.path, llm=boom).handle(1, "вопрос", None, "")[0][0], k.LLM_UNAVAILABLE)
        self.assertEqual(Bot(self.path, llm=lambda m: "  ").handle(1, "вопрос", None, "")[0][0], k.LLM_UNAVAILABLE)

    def test_long_question_is_truncated_before_llm(self):
        seen = []
        Bot(self.path, llm=lambda m: seen.append(m) or "ок").handle(1, "а" * 2000, None, "")
        self.assertEqual(len(seen[0][-1]["content"]), 500)

    def test_personal_data_not_sent_to_llm(self):
        seen = []
        bot = Bot(self.path, llm=lambda m: seen.append(m) or "ок")
        bot.handle(1, "/запись", None, "Анна"); bot.handle(1, "Мария", None, "Анна"); bot.handle(1, "maria@mail.ru", None, "Анна")
        self.assertEqual(seen, [])  # шаги записи нейросеть не видит

    def test_csv_formula_injection_is_neutralised(self):
        save_lead(self.path, 5, "=HYPERLINK(\"x\")", "+7999")
        save_lead(self.path, 6, "@SUM(1+1)", "@maria_test")
        with open(self.path, encoding="utf-8") as f:
            rows = list(csv.reader(f))
        self.assertTrue(rows[1][2].startswith("'"))
        self.assertTrue(rows[1][3].startswith("'"))
        self.assertTrue(rows[2][2].startswith("'"))   # @SUM(...) обезврежен
        self.assertEqual(rows[2][3], "@maria_test")    # обычный ник не тронут


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, text):
        with open(os.path.join(self.dir, name), "w", encoding="utf-8") as f:
            f.write(text)

    def test_loads_md_and_txt_sorted_and_ignores_others(self):
        self.write("02-b.md", "Второй")
        self.write("01-a.txt", "Первый")
        self.write("notes.pdf", "не читать")
        self.write(".hidden.md", "скрытый")
        self.write("empty.md", "   ")
        text, count, truncated = k.load_materials(self.dir)
        self.assertEqual(count, 2)
        self.assertFalse(truncated)
        self.assertLess(text.index("Первый"), text.index("Второй"))
        self.assertNotIn("не читать", text)
        self.assertNotIn("скрытый", text)

    def test_missing_folder_is_not_an_error(self):
        self.assertEqual(k.load_materials(os.path.join(self.dir, "нет")), ("", 0, False))

    def test_limit_truncates(self):
        self.write("a.md", "ж" * 300)
        self.write("b.md", "щ" * 300)
        text, count, truncated = k.load_materials(self.dir, limit=400)
        self.assertTrue(truncated)
        self.assertEqual(text.count("ж"), 300)
        self.assertEqual(text.count("щ"), 100)  # второй файл обрезан до остатка лимита

    def test_prompt_contains_rules_and_materials(self):
        self.write("faq.md", "Секретный факт 42")
        prompt, count, _ = k.build_system_prompt(self.dir)
        self.assertEqual(count, 1)
        self.assertIn("Материалы проекта", prompt)
        self.assertIn("Секретный факт 42", prompt)
        self.assertIn("Других фактов не придумывай", prompt)
        self.assertIn("совместимост", prompt)

    def test_bot_sends_custom_system_prompt_to_llm(self):
        seen = []
        bot = Bot(os.path.join(self.dir, "l.csv"), llm=lambda m: seen.append(m) or "ок", system_prompt="МОЙ ПРОМПТ")
        bot.handle(1, "вопрос", None, "")
        self.assertEqual(seen[0][0], {"role": "system", "content": "МОЙ ПРОМПТ"})

    def test_real_knowledge_folder_has_core_facts(self):
        here = os.path.dirname(os.path.abspath(__file__))
        prompt, count, truncated = k.build_system_prompt(os.path.join(here, "knowledge"))
        self.assertGreaterEqual(count, 3)
        self.assertFalse(truncated)
        for fact in ("1990", "15 000", "Расшифровщик", "Оформитель", "Сборщик"):
            self.assertIn(fact, prompt)


class FakeResp:
    def __init__(self, status=200, content="ответ"):
        self.status_code, self.ok = status, status < 400
        self._content = content
        self.text = "тело ошибки"

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


class LLMFallbackTests(unittest.TestCase):
    def call(self, responses, model="m1"):
        import llm
        calls = []
        def fake_post(url, headers=None, json=None, timeout=None):
            calls.append(json["model"])
            r = responses.pop(0)
            if isinstance(r, Exception):
                raise r
            return r
        orig, orig_sleep = llm.requests.post, llm.time.sleep
        llm.requests.post = fake_post
        llm.time.sleep = lambda _s: None
        try:
            ask = llm.make_llm("KEY", "https://openrouter.ai/api/v1", model)
            try:
                return ask([{"role": "user", "content": "q"}]), calls, None
            except RuntimeError as e:
                return None, calls, str(e)
        finally:
            llm.requests.post, llm.time.sleep = orig, orig_sleep

    def test_chain_has_user_model_first_then_fallbacks_without_duplicates(self):
        import llm
        chain = llm.model_chain("a:free, b:free", "https://openrouter.ai/api/v1")
        self.assertEqual(chain[:2], ["a:free", "b:free"])
        self.assertEqual(chain[2:], llm.OPENROUTER_FALLBACKS)
        self.assertEqual(llm.model_chain("x", "https://other.example/v1"), ["x"])

    def test_first_model_ok_no_fallback(self):
        answer, calls, err = self.call([FakeResp(200, "привет")])
        self.assertEqual((answer, calls[0:1], err), ("привет", ["m1"], None))
        self.assertEqual(len(calls), 1)

    def test_429_goes_to_next_model(self):
        answer, calls, err = self.call([FakeResp(429), FakeResp(200, "из запасной")])
        self.assertEqual(answer, "из запасной")
        self.assertEqual(len(calls), 2)

    def test_empty_answer_and_network_error_go_to_next(self):
        import requests
        answer, calls, err = self.call([FakeResp(200, "  "), requests.ConnectionError("нет сети"), FakeResp(200, "ок")])
        self.assertEqual(answer, "ок")
        self.assertEqual(len(calls), 3)

    def test_401_stops_immediately(self):
        answer, calls, err = self.call([FakeResp(401), FakeResp(200, "не должно дойти")])
        self.assertIsNone(answer)
        self.assertIn("401", err)
        self.assertEqual(len(calls), 1)

    def test_all_models_fail_raises_with_details(self):
        import llm
        n = len(llm.model_chain("m1", "https://openrouter.ai/api/v1"))
        answer, calls, err = self.call([FakeResp(429)] * (2 * n))
        self.assertIsNone(answer)
        self.assertIn("все модели недоступны", err)
        self.assertEqual(len(calls), 2 * n)  # два круга: после 429 цепочку пробуем ещё раз

    def test_second_round_can_succeed_after_rate_limit(self):
        import llm
        n = len(llm.model_chain("m1", "https://openrouter.ai/api/v1"))
        answer, calls, err = self.call([FakeResp(429)] * n + [FakeResp(200, "со второго круга")])
        self.assertEqual(answer, "со второго круга")
        self.assertEqual(len(calls), n + 1)

    def test_no_second_round_without_rate_limit(self):
        import llm
        n = len(llm.model_chain("m1", "https://openrouter.ai/api/v1"))
        answer, calls, err = self.call([FakeResp(500)] * n)
        self.assertIsNone(answer)
        self.assertEqual(len(calls), n)


class VKReconnectTests(unittest.TestCase):
    def test_events_survive_connection_reset_and_reconnect(self):
        import requests
        import vk as vkmod

        class Resp:
            def __init__(self, data): self._d = data
            def json(self): return self._d

        script = [
            requests.ConnectionError("Connection reset by peer"),
            Resp({"ts": "2", "updates": [{"type": "message_new", "object": {"message": {"text": "привет"}}}]}),
        ]
        connects = []
        client = vkmod.VK("T", 1)
        client.call = lambda method, **p: connects.append(method) or {"server": "http://x", "key": "k", "ts": "1"}
        orig_get, orig_sleep = vkmod.requests.get, vkmod.time.sleep
        def fake_get(*a, **kw):
            item = script.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        vkmod.requests.get, vkmod.time.sleep = fake_get, lambda _s: None
        try:
            msg = next(client.events())
        finally:
            vkmod.requests.get, vkmod.time.sleep = orig_get, orig_sleep
        self.assertEqual(msg["text"], "привет")
        self.assertEqual(connects.count("groups.getLongPollServer"), 2)  # после обрыва получили новый адрес

    def test_failed_codes_trigger_reconnect_and_ts_update(self):
        import vk as vkmod

        class Resp:
            def __init__(self, data): self._d = data
            def json(self): return self._d

        script = [Resp({"failed": 2}), Resp({"failed": 1, "ts": "9"}),
                  Resp({"ts": "10", "updates": [{"type": "message_new", "object": {"message": {"text": "ок"}}}]})]
        connects = []
        client = vkmod.VK("T", 1)
        client.call = lambda method, **p: connects.append(method) or {"server": "http://x", "key": "k", "ts": "1"}
        orig_get = vkmod.requests.get
        vkmod.requests.get = lambda *a, **kw: script.pop(0)
        try:
            msg = next(client.events())
        finally:
            vkmod.requests.get = orig_get
        self.assertEqual(msg["text"], "ок")
        self.assertEqual(client.ts, "10")
        self.assertEqual(len(connects), 2)


class PromptFileTests(unittest.TestCase):
    def test_prompt_has_all_blocks_in_order(self):
        text = k.SYSTEM_PROMPT
        positions = [text.index(h) for h in ("## Роль", "## Стиль", "## Задачи", "## Ограничения", "## Примеры")]
        self.assertEqual(positions, sorted(positions))

    def test_bot_name_is_substituted_everywhere(self):
        self.assertNotIn("{bot_name}", k.SYSTEM_PROMPT)
        self.assertIn(k.BOT_NAME, k.SYSTEM_PROMPT)
        greeting = k.GREETING.format(name="Анна", bot_name=k.BOT_NAME)
        self.assertIn(k.BOT_NAME, greeting)

    def test_restrictions_block_covers_required_points(self):
        restrictions = k.SYSTEM_PROMPT.split("## Ограничения")[1].split("## Примеры")[0].lower()
        for needle in ("не раскрывай", "не уходи от темы", "персональные данные", "не придумывай", "совместимост"):
            self.assertIn(needle, restrictions)

    def test_custom_prompt_file_and_name(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "p.md")
            with open(path, "w", encoding="utf-8") as f:
                f.write("Ты {bot_name}.\n")
            self.assertEqual(k.load_system_prompt(path, "Мила"), "Ты Мила.")


class MarkdownAndTypingTests(unittest.TestCase):
    def test_markdown_is_stripped(self):
        raw = "**Да**, нужен доступ.\n\n## Что входит\n* агенты\n* `промпты`\n[сайт](https://a.ru) и *важно*."
        clean = clean_markdown(raw)
        for symbol in ("**", "##", "`", "[сайт]"):
            self.assertNotIn(symbol, clean)
        self.assertIn("- агенты", clean)
        self.assertIn("сайт (https://a.ru)", clean)

    def test_plain_text_and_prices_are_untouched(self):
        text = "Цена 1990 ₽ * 2 не меняется. Путь /запись и 5-10 шагов."
        self.assertEqual(clean_markdown(text), text)

    def test_bot_returns_clean_answer_and_stores_clean_history(self):
        with tempfile.TemporaryDirectory() as d:
            bot = Bot(os.path.join(d, "l.csv"), llm=lambda m: "**Да.** Нужна подписка.")
            self.assertEqual(bot.handle(1, "Нужна подписка?", None, "")[0][0], "Да. Нужна подписка.")
            self.assertEqual(bot.history[1][-1]["content"], "Да. Нужна подписка.")

    def test_set_typing_calls_vk_and_never_raises(self):
        import vk as vkmod
        client = vkmod.VK("T", 1)
        calls = []
        client.call = lambda method, **p: calls.append((method, p)) or 1
        client.set_typing(7)
        self.assertEqual(calls[0][0], "messages.setActivity")
        self.assertEqual(calls[0][1]["type"], "typing")
        def boom(method, **p): raise vkmod.VKError("нет", 100)
        client.call = boom
        client.set_typing(7)  # не должно упасть


class HelperTests(unittest.TestCase):
    def test_contacts(self):
        for ok in ("@anna_x", "t.me/anna_x", "name@mail.ru"):
            self.assertTrue(looks_like_contact(ok), ok)
        for bad in ("привет", "@a", "name@", "12"):
            self.assertFalse(looks_like_contact(bad), bad)

    def test_vk_mention_markup_is_unwrapped(self):
        cases = {
            "@anna_example": "@anna_example",
            "@anna_example (Анна Пример)": "@anna_example",
            "[id100200300|@anna_example]": "@anna_example",
            "[id100200300|Анна] @anna_tg": "@anna_tg",
            "мой телеграм t.me/anna_tg, пишите": "t.me/anna_tg",
            "почта: name@mail.ru": "name@mail.ru",
            "  @abc_def  ": "@abc_def",
        }
        for raw, expected in cases.items():
            self.assertEqual(extract_contact(raw), expected, raw)

    def test_non_contacts_are_rejected(self):
        for raw in ("", "привет", "[id1|Анна]", "@ab", "12345", "@Evgеnia_X"):  # последняя: русская «е»
            self.assertIsNone(extract_contact(raw), raw)

    def test_lead_flow_accepts_mention_and_saves_clean_contact(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "l.csv")
            bot = Bot(path)
            bot.handle(1, "/запись", None, ""); bot.handle(1, "Евгения", None, "")
            reply, kb = bot.handle(1, "@anna_example (Анна Пример)", None, "")[0]
            self.assertIn("@anna_example", reply)
            self.assertNotIn("Скакунова)", reply)
            bot.handle(1, "Согласен(а)", "agree", "")
            with open(path, encoding="utf-8") as f:
                self.assertEqual(list(csv.reader(f))[1][3], "@anna_example")

    def test_keyboards_are_valid_json_with_payloads(self):
        for kb in (main_keyboard(), consent_keyboard()):
            data = json.loads(kb)
            for row in data["buttons"]:
                for b in row:
                    self.assertLessEqual(len(b["action"]["label"]), 40)
                    self.assertIn("cmd", json.loads(b["action"]["payload"]))


if __name__ == "__main__":
    unittest.main()
