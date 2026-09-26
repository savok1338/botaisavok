import asyncio
import logging
from dataclasses import dataclass, field
from typing import Dict, List
from google import genai
from google.genai import types, errors

import config
import database

logger = logging.getLogger(__name__)

@dataclass
class ChatTurn:
    """Одиночное сообщение в диалоге."""
    role: str  # 'user' или 'model'
    text: str


class ConversationMemoryStorage:
    """
    Хранилище истории диалогов в оперативной памяти (In-Memory).
    
    ВНИМАНИЕ:
    В текущей тестовой реализации история хранится исключительно в памяти процесса Python.
    При перезапуске или остановке бота вся история диалогов будет потеряна.
    
    Архитектура изолирована: данный класс реализует простой интерфейс, который в будущем
    можно легко заменить на адаптер для SQLite, PostgreSQL или Redis без переписывания
    остального кода бота.
    """
    def __init__(self, max_history_turns: int = 20) -> None:
        # Хранилище: user_id -> список ChatTurn
        self._storage: Dict[int, List[ChatTurn]] = {}
        # Ограничение количества последних сообщений для предотвращения разрастания контекста
        self._max_history_turns = max_history_turns

    def get_history(self, user_id: int) -> List[ChatTurn]:
        """Получить копию истории диалога пользователя."""
        return list(self._storage.get(user_id, []))

    def add_turn(self, user_id: int, role: str, text: str) -> None:
        """Добавить новое сообщение в историю пользователя."""
        if user_id not in self._storage:
            self._storage[user_id] = []
        self._storage[user_id].append(ChatTurn(role=role, text=text))
        # Ограничиваем глубину контекста
        if len(self._storage[user_id]) > self._max_history_turns:
            self._storage[user_id] = self._storage[user_id][-self._max_history_turns:]

    def clear(self, user_id: int) -> bool:
        """Очистить историю диалога конкретного пользователя."""
        if user_id in self._storage:
            del self._storage[user_id]
            return True
        return False

    def count(self, user_id: int) -> int:
        """Количество сохраненных реплик пользователя."""
        return len(self._storage.get(user_id, []))


class GeminiService:
    """
    Сервис взаимодействия с Google Gemini API через официальный SDK `google-genai`.
    """
    def __init__(self) -> None:
        # Инициализация официального клиента Google GenAI
        self._client = genai.Client(api_key=config.GEMINI_API_KEY)
        self._storage = ConversationMemoryStorage(max_history_turns=20)
        self._primary_model = config.GEMINI_TEXT_MODEL
        self._fallback_model = config.GEMINI_FALLBACK_TEXT_MODEL
        self._timeout = config.REQUEST_TIMEOUT

    def reset_history(self, user_id: int) -> bool:
        """
        Полностью очищает историю сообщений конкретного пользователя.
        """
        return self._storage.clear(user_id)

    def get_history_length(self, user_id: int) -> int:
        """Возвращает число сообщений в текущей истории пользователя."""
        return self._storage.count(user_id)

    def _build_gemini_contents(self, history: List[ChatTurn], new_prompt: str) -> List[types.Content]:
        """
        Преобразует локальную историю и новый запрос в формат Google GenAI types.Content.
        """
        contents: List[types.Content] = []
        for turn in history:
            role = "user" if turn.role == "user" else "model"
            contents.append(
                types.Content(
                    role=role,
                    parts=[types.Part.from_text(text=turn.text)]
                )
            )
        # Добавляем текущий запрос пользователя
        contents.append(
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=new_prompt)]
            )
        )
        return contents

    async def _send_request_with_retry(self, model: str, contents: List[types.Content]) -> str:
        """
        Выполняет асинхронный запрос к модели с автоматическими повторами при временных ошибках.
        """
        last_exception = None
        max_retries = 2
        
        for attempt in range(max_retries + 1):
            try:
                # Отключаем автоматический вызов функций (AFC), так как бот работает в режиме чистого диалога
                system_prompt = database.get_system_prompt()
                config_opts = types.GenerateContentConfig(
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                    temperature=0.7,
                    system_instruction=system_prompt if system_prompt else None,
                )
                
                response = await asyncio.wait_for(
                    self._client.aio.models.generate_content(
                        model=model,
                        contents=contents,
                        config=config_opts,
                    ),
                    timeout=self._timeout
                )
                
                # Проверяем наличие текста в ответе
                if response.text:
                    return response.text.strip()
                
                # Если ответ был заблокирован фильтрами безопасности или пуст
                if response.candidates:
                    first_cand = response.candidates[0]
                    finish_reason = getattr(first_cand, "finish_reason", None)
                    logger.warning("Gemini вернул пустой текст. Finish reason: %s", finish_reason)
                    return "Ответ не может быть предоставлен моделью из-за настроек фильтрации содержимого."
                
                return "Получен пустой ответ от AI-модели."
                
            except (errors.ServerError, errors.APIError) as err:
                last_exception = err
                logger.warning("Gemini API ошибка (попытка %d/%d): %s", attempt + 1, max_retries + 1, err)
                if attempt < max_retries:
                    await asyncio.sleep(1.5 * (attempt + 1))
            except asyncio.TimeoutError:
                last_exception = TimeoutError(f"Таймаут запроса к Gemini ({self._timeout}с)")
                logger.warning("Gemini API timeout (попытка %d/%d)", attempt + 1, max_retries + 1)
                if attempt < max_retries:
                    await asyncio.sleep(1.0)
            except Exception as e:
                # Клиентские ошибки (400, 404, 403) повторно не шлем
                last_exception = e
                break
                
        raise last_exception or RuntimeError("Неизвестная ошибка при запросе к Gemini API")

    async def generate_text(self, user_id: int, prompt: str) -> str:
        """
        Основной метод генерации ответа в чате с сохранением контекста.
        """
        logger.info("[INFO] Gemini request started for user_id=%d", user_id)
        
        # Получаем сохраненную историю диалога пользователя
        history = self._storage.get_history(user_id)
        contents = self._build_gemini_contents(history, prompt)
        
        reply_text = ""
        try:
            # 1. Сначала пробуем основную модель
            reply_text = await self._send_request_with_retry(self._primary_model, contents)
        except Exception as primary_err:
            logger.warning("[WARNING] Основная модель %s вернула ошибку: %s. Пробуем резервную модель %s...",
                           self._primary_model, primary_err, self._fallback_model)
            try:
                # 2. При сбое пробуем резервную легковесную модель
                reply_text = await self._send_request_with_retry(self._fallback_model, contents)
            except Exception as fallback_err:
                logger.error("[ERROR] Gemini API error: %s", fallback_err)
                raise fallback_err

        # Сохраняем диалог в память
        self._storage.add_turn(user_id=user_id, role="user", text=prompt)
        self._storage.add_turn(user_id=user_id, role="model", text=reply_text)
        
        logger.info("[INFO] Gemini response received for user_id=%d", user_id)
        return reply_text
