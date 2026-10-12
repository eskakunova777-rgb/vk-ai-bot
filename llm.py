"""Клиент нейросети: любой OpenAI-совместимый адрес (по умолчанию OpenRouter, бесплатные модели).

Бесплатные модели OpenCode Zen из своих скриптов использовать нельзя: сервис отвечает,
что бесплатный тариф доступен только внутри OpenCode, а Fledge Alpha закрыта для России.

Бесплатные модели OpenRouter часто упираются в общий лимит (HTTP 429), поэтому бот пробует
по очереди несколько моделей: сначала из LLM_MODEL (можно через запятую), затем запасные."""
import sys
import time

import requests

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "google/gemma-4-31b-it:free"
# Проверены 07.10.2026: отвечают по-русски без «рассуждений вслух».
RETRY_DELAY = 4  # секунд до второго круга, если модели были перегружены (HTTP 429)
OPENROUTER_FALLBACKS = ["poolside/laguna-s-2.1:free", "nvidia/nemotron-3-ultra-550b-a55b:free"]


def model_chain(model: str, base: str) -> list:
    chain = [m.strip() for m in (model or DEFAULT_MODEL).split(",") if m.strip()]
    if "openrouter.ai" in base:
        chain += [m for m in OPENROUTER_FALLBACKS if m not in chain]
    return chain


def make_llm(api_key: str, base_url: str = "", model: str = "", timeout: int = 30):
    base = (base_url or DEFAULT_BASE_URL).rstrip("/")
    chain = model_chain(model, base)

    def ask(messages: list) -> str:
        errors = []
        for attempt in range(2):
            rate_limited = False
            for m in chain:
                try:
                    resp = requests.post(
                        f"{base}/chat/completions",
                        headers={"Authorization": f"Bearer {api_key}"},
                        json={"model": m, "messages": messages, "temperature": 0.3, "max_tokens": 400},
                        timeout=timeout,
                    )
                except requests.RequestException as e:
                    errors.append(f"{m}: {e}")
                    continue
                if resp.status_code == 401:
                    raise RuntimeError(f"HTTP 401: ключ нейросети не принят ({resp.text[:150]})")
                if not resp.ok:
                    rate_limited = rate_limited or resp.status_code == 429
                    errors.append(f"{m}: HTTP {resp.status_code}")
                    continue
                try:
                    answer = (resp.json()["choices"][0]["message"]["content"] or "").strip()
                except (ValueError, KeyError, IndexError, TypeError):
                    answer = ""
                if answer:
                    if m != chain[0]:
                        print(f"Нейросеть: ответила запасная модель {m}", file=sys.stderr)
                    return answer
                errors.append(f"{m}: пустой ответ")
            if attempt == 0 and rate_limited:
                time.sleep(RETRY_DELAY)  # даём лимитам освободиться и пробуем цепочку ещё раз
                continue
            break
        raise RuntimeError("все модели недоступны: " + "; ".join(errors))

    ask.model = chain[0]
    ask.chain = chain
    return ask
