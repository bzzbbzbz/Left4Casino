import json
import logging
import os
import random

from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv()

logger = logging.getLogger(__name__)
DEFAULT_AI_TIMEOUT_SECONDS = 20.0

_PLACEHOLDER_API_KEYS = {
    "",
    "dummy",
    "replace-me",
    "replaceme",
    "change-me",
    "changeme",
    "your-api-key",
    "yourapikey",
    "your-api-key-here",
    "your-openai-api-key",
    "your-openrouter-api-key",
    "api-key",
    "apikey",
    "placeholder",
    "none",
    "null",
}


def _normalize_api_key_for_validation(api_key: str | None) -> str:
    return (api_key or "").strip().lower().replace("_", "-").replace(" ", "-")


def _is_placeholder_api_key(api_key: str | None) -> bool:
    normalized = _normalize_api_key_for_validation(api_key)
    if normalized in _PLACEHOLDER_API_KEYS:
        return True
    return normalized.startswith("<") and normalized.endswith(">")


def _exception_type(error: Exception) -> str:
    return type(error).__name__


class AIServiceError(RuntimeError):
    """Sanitized AI provider failure safe to surface to handlers/logs."""


def _require_non_empty_str(data: dict, *keys: str) -> str:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raise AIServiceError("AI response generation returned malformed schema")


def _require_number(data: dict, key: str) -> int:
    if key not in data:
        raise AIServiceError("AI response generation returned malformed schema")
    value = data[key]
    if isinstance(value, bool):
        raise AIServiceError("AI response generation returned malformed schema")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.lstrip("+-").isdigit():
            return int(stripped)
    raise AIServiceError("AI response generation returned malformed schema")


def _normalize_completion_data(data: dict, text: str) -> dict:
    completion_data = data.get("completion_data")
    if not isinstance(completion_data, dict):
        raise AIServiceError("AI response generation returned malformed schema")
    done = completion_data.get("done")
    if not isinstance(done, bool):
        raise AIServiceError("AI response generation returned malformed schema")
    score = _require_number(completion_data, "score")
    reward = _require_number(completion_data, "reward")
    comment = completion_data.get("comment")
    if not isinstance(comment, str) or not comment.strip():
        raise AIServiceError("AI response generation returned malformed schema")
    return {"done": done, "score": score, "reward": reward, "comment": comment.strip()}


def _parse_ai_response_payload(clean_content: str) -> tuple[str, dict]:
    try:
        data = json.loads(clean_content)
    except json.JSONDecodeError as error:
        raise AIServiceError("AI response generation returned invalid JSON") from error
    if not isinstance(data, dict):
        raise AIServiceError("AI response generation returned malformed schema")
    text = _require_non_empty_str(data, "content", "text", "comment")
    completion_data = _normalize_completion_data(data, text)
    reward = max(1, min(100, int(completion_data["reward"])))
    completion_data = {**completion_data, "reward": reward}
    return text, completion_data


class AIClient:
    def __init__(self, config):
        self.config = config
        self.provider = config.provider.lower().strip()
        self.client = None

        if self.provider == "mock":
            self.model_name = config.model
            return

        openrouter_key = os.getenv("OPENROUTER_API_KEY")
        openai_key = os.getenv("OPENAI_API_KEY")
        api_key = config.api_key
        base_url = None
        self.model_name = config.model

        if self.provider == "openrouter":
            api_key = openrouter_key or config.api_key
            base_url = "https://openrouter.ai/api/v1"
            if "/" not in self.model_name:
                self.model_name = f"openai/{self.model_name}"
        elif self.provider == "openai":
            api_key = openai_key or config.api_key
        else:
            raise ValueError(f"Unsupported AI provider: {config.provider}")

        if _is_placeholder_api_key(api_key):
            raise ValueError(f"AI provider '{self.provider}' requires a real API key")

        if base_url:
            self.client = AsyncOpenAI(
                base_url=base_url,
                api_key=api_key,
                timeout=DEFAULT_AI_TIMEOUT_SECONDS,
            )
        else:
            self.client = AsyncOpenAI(api_key=api_key, timeout=DEFAULT_AI_TIMEOUT_SECONDS)

    async def generate_initial_greeting(self) -> str:
        if self.provider == "mock":
            return "Эй, ты! Хочешь денег? Удиви меня!"

        try:
            tasks = [
                "рассказать анекдот",
                "загадать игроку загадку",
                "загадать игроку загадку",
                "сделать комплимент банкиру",
                "произнести тост",
                "придумать оправдание проигрышу",
            ]
            topics = [
                "анонимные имиджборды",
                "рэп-батл",
                "2ch",
                "зумеры",
                "казино",
                "коллекторы",
                "ставки",
                "киберспорт",
                "криптовалюты",
                "Илья Мэддисон",
                "русские ютуберы",
                "русский рэп",
                "игра STALKER",
                "крафтовое пиво",
                "кино",
            ]

            selected_task = random.choice(tasks)

            if random.random() < 0.7:
                topic_part = f"Используй тему: {random.choice(topics)}."
            else:
                topic_part = "Придумай случайную тему, актуальную для молодого человека в России."

            prompt = (
                "Ты — циничный и хитрый банкир в казино. Твой характер: смесь Джокера и уставшего коллектора. "
                "Ты не хочешь давать кредит, поэтому даешь задание.\n\n"
                f"ЗАДАНИЕ: {selected_task}\n"
                f"КОНТЕКСТ: {topic_part}\n\n"
                "ИНСТРУКЦИЯ:\n"
                "1. Сформулируй требование к игроку ОДНОЙ простой фразой.\n"
                "2. Если задание 'ЗАГАДКА' — можешь быть изобретательным и сложным.\n"
                "3. Если задание 'ТОСТ', 'АНЕКДОТ' или 'КОМПЛИМЕНТ' — ЗАПРЕЩЕНО нагромождать условия. Используй либо тему, либо стиль, но не все сразу.\n"
                "   ПЛОХО: 'Расскажи анекдот про студента, как будто ты Тарантино и у тебя экзамен'.\n"
                "   ХОРОШО: 'Расскажи анекдот про студента на экзамене'.\n"
                "4. Не пиши 'Задание: ...', не здоровайся. Сразу требуй.\n\n"
                "ПРИМЕРЫ ХОРОШИХ ОТВЕТОВ:\n"
                "- (Задание: анекдот, Тема: русский рэп) -> 'Расскажи мне анекдот про Тимати или Басту. И чтобы было смешно, йоу.'\n"
                "- (Задание: комплимент, Тема: Илья Мэддисон) -> 'Похвали меня так, как будто ты Илья Мэддисон на обзоре шедевра 10 из 10.'\n"
                "- (Задание: оправдание, Тема: STALKER) -> 'Объясни мне, куда делись деньги. Говори так, будто оправдываешься перед Сидоровичем за потерянный хабар.'\n"
                "- (Задание: загадка, Тема: коллекторы) -> 'Отгадай загадку: в дверь стучат, но не гости, кто это?.'\n\n"
                "Твой ответ (только текст требования):"
            )

            if self.client is None:
                raise RuntimeError("AI client is not initialized")

            response = await self.client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "system", "content": prompt}],
                temperature=0.6,
            )
            content = response.choices[0].message.content.strip()
            if not content:
                raise AIServiceError("AI greeting generation returned empty content")
            return content

        except Exception as e:
            logger.error("Error generating greeting", extra={"error_type": _exception_type(e)})
            if isinstance(e, AIServiceError):
                raise
            raise AIServiceError("AI greeting generation failed") from None

    def _calculate_ai_score(self, text: str) -> int:
        """
        Calculates a heuristic score (0-100) indicating probability of AI generation.
        Based on typography, length, and structure.
        """
        score = 0

        # 1. Typography check
        score += text.count("—") * 25  # Em-dash is very AI-like in chat
        score += text.count("«") * 20  # Chevron quotes
        score += text.count("»") * 20

        # 2. Structure check
        if "\n\n" in text:
            score += 15  # Paragraphs
        if text.strip().startswith(("•", "-", "*")) or "\n-" in text or "\n•" in text:
            score += 20  # Lists

        # 3. Length check
        if len(text) > 300:
            score += 20
        elif len(text) > 150:
            score += 10

        return min(100, score)

    async def generate_response(self, history: list[dict]) -> dict:
        """
        Processes the user's answer and returns a reward based on strict evaluation.
        """
        if self.provider == "mock":
            return {
                "content": "Ладно, держи немного фишек и не позорься.",
                "completion_data": {
                    "done": True,
                    "score": 10,
                    "reward": 15,
                    "comment": "mock",
                },
            }

        try:
            # Extract user's last message
            user_message = "..."
            bot_task = "Неизвестное задание"

            # Iterate backwards to find user message and the preceding assistant message
            found_user = False
            for i in range(len(history) - 1, -1, -1):
                msg = history[i]
                if msg["role"] == "user" and not found_user:
                    user_message = msg["content"]
                    found_user = True
                    # Look for the assistant message before this user message
                    if i > 0 and history[i - 1]["role"] == "assistant":
                        bot_task = history[i - 1]["content"]
                    break

            # Calculate AI suspicion score
            ai_score = self._calculate_ai_score(user_message)
            ai_warning = ""

            if ai_score > 50:
                ai_warning = f"СИСТЕМНОЕ СООБЩЕНИЕ: Технический анализ выявил ВЫСОКУЮ вероятность (score {ai_score}), что это текст нейросети (типографика, структура, объем). Если ответ скучный и правильный — ставь оценку 'МУСОР' или 'СКУКА'."
            elif ai_score > 20:
                ai_warning = f"СИСТЕМНОЕ СООБЩЕНИЕ: Есть признаки генерации (score {ai_score}). Будь строг к 'воде'."
            else:
                ai_warning = f"Технический анализ: Текст похож на живой (score {ai_score})."

            # Prompt to evaluate (accept) the answer
            system_prompt = (
                "Ты — веселый Джокер в казино, оценивающий выполнение задания кредитора. "
                f'ЗАДАНИЕ БЫЛО: "{bot_task}". '
                f'ОТВЕТ ИГРОКА: "{user_message}". \n\n'
                f"{ai_warning}\n\n"
                "ТВОЯ ЗАДАЧА: Оцени ответ в 3 шага:\n"
                "1. ПРОВЕРЬ КОНТЕКСТ: Понимает ли игрок тему? Учитывай культурные отсылки (фильмы, музыка, мемы России/СНГ). Для загадок тема вторична, оценивай креативность.\n"
                "2. ОЦЕНИ КРЕАТИВ: Есть ли юмор, находчивость или старания? Распознавай мета-шутки и второй слой и оценивай их выше.\n"
                "3. ПРОВЕРЬ НА AI: Признаки AI-генерации (идеальная грамматика, формальные кавычки/тире, академический стиль без сленга).\n\n"
                "ШКАЛА ОЦЕНКИ:\n"
                "МУСОР (1-19): Полный игнор темы, требование денег, явная лень или копипаст.\n"
                "СКУКА (20-39): Формальный ответ без креатива, AI-генерация, 'для галочки'.\n"
                "КРЕАТИВ (40-69): Соблюдена тема/стиль, есть юмор или находчивость.\n"
                "ЗОЛОТО (70-100): Гениальная шутка, неожиданная отсылка, вызывает смех.\n\n"
                "ПРАВИЛА:\n"
                "Сравнивай с baseline: ответ лучше, чем 'просто дай деньги'? Лучше, чем сухой пересказ задания? Если да - минимум 50.\n"
                "- Не штрафуй за грамматические ошибки в творческих ответах, сленг, короткие ответы (при соответствии теме).\n"
                "- Штрафуй за AI-шаблоны, игнор темы, отсутствие попыток.\n\n"
                "ПРИМЕРЫ:\n"
                "- 'Расскажи тост про Тарантино' - 'мистер розовый, давайте выпьем за футфетиш' → 95 (отсылка к Тарантино, креативно)\n"
                "- 'Разгадай загадку: что в казино всегда в плюсе, но никогда не выигрывает?' — 'Температура помещения' → 96\n"
                "- Загадка — точное одно слово по сути → 80–100\n"
                "- Идеально оформленный длинный текст без души → 25 (AI-генерация)\n"
                "- Короткий, но меткий ответ по теме → 60+ (ценить старания и находчивость)\n\n"
                "КОММЕНТАРИИ: Краткие, соответствуют оценке - от критики до уважения.\n\n"
                'Формат ответа строго JSON: { "content": "Ответ пользователю", "completion_data": { "done": true, "score": число, "reward": число, "comment": "краткий комментарий" } }'
            )

            messages = [{"role": "system", "content": system_prompt}]

            if self.client is None:
                raise RuntimeError("AI client is not initialized")

            response = await self.client.chat.completions.create(
                model=self.model_name, messages=messages, temperature=0.4
            )

            content = response.choices[0].message.content

            # Try to parse JSON
            try:
                # Simple cleanup to handle code blocks
                clean_content = content
                if "```" in clean_content:
                    match = clean_content.split("```")
                    # Check if there is json block
                    for block in match:
                        if block.strip().startswith("json"):
                            clean_content = block.strip()[4:]
                            break
                        elif block.strip().startswith("{"):
                            clean_content = block.strip()
                            break

                # Fallback cleanup for non-codeblock json
                start = clean_content.find("{")
                end = clean_content.rfind("}")
                if start != -1 and end != -1:
                    clean_content = clean_content[start : end + 1]

                text, completion = _parse_ai_response_payload(clean_content)
            except AIServiceError:
                logger.warning("Failed to parse JSON from AI response")
                raise

            return {
                "content": text,
                "completion_data": completion,
            }

        except Exception as e:
            logger.error("Error generating response", extra={"error_type": _exception_type(e)})
            if isinstance(e, AIServiceError):
                raise
            raise AIServiceError("AI response generation failed") from None
