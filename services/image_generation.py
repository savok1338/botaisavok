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
        Запрос генерации изображения через Google Imagen 3 или Gemini Multimodal Image.
        Поддерживает:
        - imagen-3.0-generate-002 (Google Imagen 3)
        - gemini-3-pro-image / nano-banana-pro-preview / gemini-3.1-flash-image
        """
        english_prompt = await self._translate_prompt(prompt)

        # 1. Если выбрана модель Imagen
        if "imagen" in self._gemini_model.lower():
            config_opts = types.GenerateImagesConfig(
                number_of_images=1,
                output_mime_type="image/jpeg",
                aspect_ratio="1:1",
                person_generation="ALLOW_ADULT",
                add_watermark=False,
            )
            response = await asyncio.wait_for(
                self._client.aio.models.generate_images(
                    model=self._gemini_model,
                    prompt=english_prompt,
                    config=config_opts,
                ),
                timeout=self._timeout,
            )
            if response and response.generated_images:
                for gen_img in response.generated_images:
                    if gen_img.image and gen_img.image.image_bytes:
                        return gen_img.image.image_bytes
        # 2. Если выбрана модель линейки Gemini / Nano-Banana
        else:
            config_opts = types.GenerateContentConfig(
                response_modalities=["IMAGE"],
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            )
            response = await asyncio.wait_for(
                self._client.aio.models.generate_content(
                    model=self._gemini_model,
                    contents=english_prompt,
                    config=config_opts,
                ),
                timeout=self._timeout,
            )
            if response and response.candidates:
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

    def _remove_watermark(self, image_bytes: bytes) -> bytes:
        """
        Удаляет водяной знак Pollinations в нижнем правом углу,
        аккуратно обрезает нижнюю кромку и повышает резкость и разрешение.
        """
        try:
            import io
            from PIL import Image, ImageEnhance
            img = Image.open(io.BytesIO(image_bytes))
            w, h = img.size
            if h > 100:
                # Обрезаем нижнюю кромку с гарантированным запасом (50 пикселей или 7% высоты),
                # чтобы стереть любой след водяного знака pollinations.ai
                crop_bottom = max(50, int(h * 0.07))
                cropped = img.crop((0, 0, w, h - crop_bottom))
                cw, ch = cropped.size

                # Масштабируем до 1024px через Lanczos для четкости
                target_w = 1024
                target_h = int(target_w * (ch / cw))
                upscaled = cropped.resize((target_w, target_h), Image.Resampling.LANCZOS)

                # Повышаем резкость, убирая замыленность
                enhancer = ImageEnhance.Sharpness(upscaled)
                sharpened = enhancer.enhance(1.25)

                output = io.BytesIO()
                sharpened.save(output, format="JPEG", quality=95)
                return output.getvalue()
        except Exception as e:
            logger.warning("[WARNING] Не удалось обработать водяной знак / резкость: %s", e)
        return image_bytes

    async def _generate_via_fallback(self, prompt: str) -> bytes:
        """
        Резервный генератор через открытый высокопроизводительный AI-эндпоинт (Flux/SDXL).
        Используется, когда у пользователя бесплатный ключ Gemini без привязки карты к Google Cloud.
        """
        logger.info("[INFO] Используется резервный генератор изображений высокой четкости...")
        
        # 1. Переводим русский промпт на английский, чтобы нейросеть поняла суть, а не рисовала случайного кота
        english_prompt = await self._translate_prompt(prompt)
        
        # 2. Усиливаем промпт описанием качества, резкости и стиля
        enhanced_prompt = f"{english_prompt}, sharp focus, photorealistic, 8k, detailed, professional photography, masterpiece"
        safe_prompt = aiohttp.helpers.quote(enhanced_prompt)
        
        import random
        seed = random.randint(1, 999999)
        
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        proxy_url = getattr(config, "PROXY_URL", None) or os.getenv("HTTP_PROXY") or None

        # Пробуем FLUX с коротким таймаутом (12с). Если очередь перегружена — сразу берем быстрый режим
        url_flux = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=1024&height=1024&seed={seed}&model=flux&nologo=true"
        try:
            flux_timeout = aiohttp.ClientTimeout(total=12)
            async with aiohttp.ClientSession(timeout=flux_timeout) as session:
                async with session.get(url_flux, headers=headers, proxy=proxy_url) as resp:
                    if resp.status == 200:
                        raw_bytes = await resp.read()
                        if raw_bytes and len(raw_bytes) > 5000:
                            return self._remove_watermark(raw_bytes)
        except Exception as flux_err:
            logger.info("[INFO] FLUX режим пропущен (%s), переход на быстрый генератор...", flux_err)

        # Быстрый генератор
        url_fast = f"https://image.pollinations.ai/prompt/{safe_prompt}?seed={seed}&nologo=true"
        fast_timeout = aiohttp.ClientTimeout(total=self._timeout)
        async with aiohttp.ClientSession(timeout=fast_timeout) as session:
            async with session.get(url_fast, headers=headers, proxy=proxy_url) as resp:
                if resp.status != 200:
                    raise ImageGenerationError(f"HTTP ошибка генератора: {resp.status}")
                raw_bytes = await resp.read()
                if not raw_bytes:
                    raise ImageGenerationError("Генератор вернул пустые данные.")
                return self._remove_watermark(raw_bytes)

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
