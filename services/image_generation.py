import asyncio
import base64
import logging
import os
from typing import Optional
import aiohttp
from google import genai
from google.genai import types, errors

import config

logger = logging.getLogger(__name__)


class ImageGenerationError(Exception):
    """Базовое исключение при ошибке генерации изображения."""
    pass


class ImageQuotaError(ImageGenerationError):
    """Исключение при исчерпании квоты или отсутствии биллинга в Google AI Studio."""
    pass


class ImageGenerationService:
    """
    Сервис генерации изображений.
    
    Поддерживает:
    1. Официальную генерацию через Google Gemini Developer API (модели с поддержкой изображений:
       gemini-2.5-flash-image или imagen-3.0).
    2. Автоматический прозрачный fallback на открытый high-res движок при отсутствии
       платного аккаунта в Google AI Studio (на бесплатном тарифе Google выставляет
       limit: 0 для генерации картинок).
    """
    def __init__(self) -> None:
        self._client = genai.Client(api_key=config.GEMINI_API_KEY)
        self._gemini_model = config.GEMINI_IMAGE_MODEL
        self._fallback_enabled = config.ENABLE_FREE_IMAGE_FALLBACK
        self._timeout = config.REQUEST_TIMEOUT

    async def _generate_via_gemini(self, prompt: str) -> Optional[bytes]:
        """
        Запрос генерации изображения через Google GenAI SDK.
        """
        config_opts = types.GenerateContentConfig(
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

        response = await asyncio.wait_for(
            self._client.aio.models.generate_content(
                model=self._gemini_model,
                contents=prompt,
                config=config_opts,
            ),
            timeout=self._timeout,
        )

        if not response.candidates:
            return None

        # Ищем часть ответа, содержащую inline-изображение (bytes или base64)
        for part in response.candidates[0].content.parts:
            if getattr(part, "inline_data", None) and part.inline_data.data:
                raw_data = part.inline_data.data
                if isinstance(raw_data, bytes):
                    return raw_data
                if isinstance(raw_data, str):
                    return base64.b64decode(raw_data)
        
        return None

    async def _translate_prompt(self, text: str) -> str:
        """
        Переводит русский текст запроса на английский язык,
        так как нейросети генерации картинок понимают только английский.
        """
        # Если в тексте нет кириллицы, перевод не нужен
        if not any('\u0400' <= char <= '\u04FF' for char in text):
            return text

        try:
            url = "https://api.mymemory.translated.net/get"
            params = {
                "q": text,
                "langpair": "ru|en"
            }
            client_timeout = aiohttp.ClientTimeout(total=6)
            proxy_url = getattr(config, "PROXY_URL", None) or os.getenv("HTTP_PROXY") or None
            async with aiohttp.ClientSession(timeout=client_timeout) as session:
                async with session.get(url, params=params, proxy=proxy_url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        translated = data.get("responseData", {}).get("translatedText", "")
                        if translated and not translated.startswith("MYMEMORY WARNING"):
                            cleaned = translated.strip()
                            for prefix in ["make a ", "draw a ", "create a ", "generate a ", "picture of a ", "make ", "draw ", "create "]:
                                if cleaned.lower().startswith(prefix):
                                    cleaned = cleaned[len(prefix):]
                            logger.info("[INFO] Промпт переведен на английский: '%s' -> '%s'", text, cleaned)
                            return cleaned
        except Exception as e:
            logger.warning("[WARNING] Ошибка перевода промпта: %s", e)

        return text

    async def _generate_via_fallback(self, prompt: str) -> bytes:
        """
        Резервный генератор через открытый высокопроизводительный AI-эндпоинт (Flux/SDXL).
        Используется, когда у пользователя бесплатный ключ Gemini без привязки карты к Google Cloud.
        """
        logger.info("[INFO] Используется резервный генератор изображений...")
        
        # 1. Переводим русский промпт на английский, чтобы нейросеть поняла суть, а не рисовала случайного кота
        english_prompt = await self._translate_prompt(prompt)
        
        # 2. Усиливаем промпт описанием качества
        enhanced_prompt = f"{english_prompt}, detailed, high quality, 3d render"
        safe_prompt = aiohttp.helpers.quote(enhanced_prompt)
        
        import random
        seed = random.randint(1, 999999)
        url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=1024&height=1024&seed={seed}&nologo=true"
        
        client_timeout = aiohttp.ClientTimeout(total=self._timeout)
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        
        proxy_url = getattr(config, "PROXY_URL", None) or os.getenv("HTTP_PROXY") or None
        async with aiohttp.ClientSession(timeout=client_timeout) as session:
            async with session.get(url, headers=headers, proxy=proxy_url) as resp:
                if resp.status != 200:
                    raise ImageGenerationError(f"HTTP ошибка генератора: {resp.status}")
                image_bytes = await resp.read()
                if not image_bytes:
                    raise ImageGenerationError("Генератор вернул пустые данные.")
                return image_bytes

    async def generate_image(self, prompt: str) -> bytes:
        """
        Главный метод генерации изображения по текстовому описанию.
        Возвращает байты изображения (JPEG / PNG).
        """
        logger.info("[INFO] Image generation started. Prompt: '%s'", prompt[:60])
        
        # 1. Попытка через официальный Gemini API
        try:
            image_bytes = await self._generate_via_gemini(prompt)
            if image_bytes:
                logger.info("[INFO] Image generation completed successfully via Gemini API")
                return image_bytes
            logger.warning("[WARNING] Gemini не вернул изображение в кандидатах.")
        except errors.ClientError as ce:
            # Ошибка 429 RESOURCE_EXHAUSTED с limit: 0 — стандартное поведение Google для бесплатного тарифа
            if ce.code == 429 and "limit: 0" in str(ce):
                logger.warning(
                    "[INFO] Google Gemini требует платный аккаунт (Billing) для генерации изображений: %s",
                    ce.message
                )
            else:
                logger.warning("[WARNING] Gemini ClientError при генерации: %s", ce)
        except Exception as e:
            logger.warning("[WARNING] Ошибка обращения к Gemini Image API: %s", e)

        # 2. Если Gemini недоступен или квота 0, используем резервный генератор при включенном флаге
        if self._fallback_enabled:
            try:
                fallback_bytes = await self._generate_via_fallback(prompt)
                logger.info("[INFO] Image generation completed via fallback engine")
                return fallback_bytes
            except Exception as fb_err:
                logger.error("[ERROR] Fallback image generation failed: %s", fb_err)
                raise ImageGenerationError(f"Не удалось сгенерировать изображение: {fb_err}")
        
        raise ImageQuotaError(
            "Генерация изображений через Gemini API требует подключенного платежного аккаунта "
            "Google AI Studio (квота Free Tier: 0). Включите ENABLE_FREE_IMAGE_FALLBACK=true в .env "
            "для бесплатной генерации."
        )
