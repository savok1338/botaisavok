import asyncio
import base64
import io
import logging
import os
import random
from typing import Optional, Tuple
import aiohttp
from PIL import Image, ImageEnhance
from google import genai
from google.genai import types, errors

import config
import database

logger = logging.getLogger(__name__)


class ImageGenerationError(Exception):
    """Базовое исключение при ошибке генерации изображения."""
    pass


class ImageQuotaError(ImageGenerationError):
    """Исключение при исчерпании квоты или отсутствии биллинга в Google AI Studio."""
    pass


class ImageGenerationService:
    """
    Сервис генерации изображений с поддержкой:
    1. Моделей Google Gemini / Pro:
       - nano-banana-pro-preview
       - gemini-3-pro-image
       - gemini-3.1-flash-image
       - imagen-3.0-generate-002
    2. Открытых высокодетализированных фотореалистичных движков:
       - flux-realism (фотореализм 8K)
       - flux (художественный)
       - turbo (быстрый)
    """
    def __init__(self) -> None:
        self._client = genai.Client(api_key=config.GEMINI_API_KEY)
        self._fallback_enabled = config.ENABLE_FREE_IMAGE_FALLBACK
        self._timeout = config.REQUEST_TIMEOUT

    async def _translate_prompt(self, text: str) -> str:
        """
        Переводит русский текст запроса на английский язык с помощью Gemini API.
        Исключает любые сбои бесплатных веб-переводчиков и гарантирует понимание
        диффузионными нейросетями.
        """
        if not any('\u0400' <= char <= '\u04FF' for char in text):
            return text

        try:
            translation_prompt = (
                "Translate this image generation prompt from Russian into a clear, "
                "vivid, descriptive English prompt for text-to-image AI. "
                "Do not include quotes, preamble or commentary, return ONLY the translated English prompt:\n\n"
                f"{text}"
            )
            res = await self._client.aio.models.generate_content(
                model="gemini-3.5-flash-lite",
                contents=translation_prompt,
            )
            if res and res.text:
                cleaned = res.text.strip().strip('"').strip("'")
                logger.info("[INFO] Промпт переведен через Gemini: '%s' -> '%s'", text, cleaned)
                return cleaned
        except Exception as e:
            logger.warning("[WARNING] Gemini перевод промпта не удался: %s, пробуем веб-перевод...", e)

        # Резервный перевод через MyMemory если Gemini API временно недоступен
        try:
            url = "https://api.mymemory.translated.net/get"
            params = {"q": text, "langpair": "ru|en"}
            client_timeout = aiohttp.ClientTimeout(total=4)
            proxy_url = getattr(config, "PROXY_URL", None) or os.getenv("HTTP_PROXY") or None
            async with aiohttp.ClientSession(timeout=client_timeout) as session:
                async with session.get(url, params=params, proxy=proxy_url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        translated = data.get("responseData", {}).get("translatedText", "")
                        if translated and not translated.startswith("MYMEMORY WARNING"):
                            return translated.strip()
        except Exception:
            pass

        return text

    def _remove_watermark(self, image_bytes: bytes) -> bytes:
        """
        Удаляет водяной знак в нижнем правом углу,
        аккуратно обрезает нижнюю кромку и повышает резкость и разрешение через Lanczos.
        """
        try:
            img = Image.open(io.BytesIO(image_bytes))
            w, h = img.size
            if h > 100:
                # Обрезаем нижнюю кромку с гарантированным запасом (50 пикселей или 7% высоты),
                # чтобы гарантированно стереть водяной знак
                crop_bottom = max(50, int(h * 0.07))
                cropped = img.crop((0, 0, w, h - crop_bottom))
                cw, ch = cropped.size

                # Масштабируем до 1024px через Lanczos для максимальной четкости
                target_w = 1024
                target_h = int(target_w * (ch / cw))
                upscaled = cropped.resize((target_w, target_h), Image.Resampling.LANCZOS)

                # Повышаем резкость на 25%, убирая замыленность
                enhancer = ImageEnhance.Sharpness(upscaled)
                sharpened = enhancer.enhance(1.25)

                output = io.BytesIO()
                sharpened.save(output, format="JPEG", quality=95)
                return output.getvalue()
        except Exception as e:
            logger.warning("[WARNING] Не удалось обработать водяной знак / резкость: %s", e)
        return image_bytes

    async def _generate_via_gemini(self, model_name: str, english_prompt: str) -> Optional[bytes]:
        """
        Генерация изображения через Google GenAI SDK.
        Поддерживает:
        - Imagen (imagen-3.0-generate-002)
        - Gemini / Nano-Banana (gemini-3-pro-image, nano-banana-pro-preview, gemini-3.1-flash-image)
        """
        if "imagen" in model_name.lower():
            config_opts = types.GenerateImagesConfig(
                number_of_images=1,
                output_mime_type="image/jpeg",
                aspect_ratio="1:1",
                person_generation="ALLOW_ADULT",
                add_watermark=False,
            )
            response = await asyncio.wait_for(
                self._client.aio.models.generate_images(
                    model=model_name,
                    prompt=english_prompt,
                    config=config_opts,
                ),
                timeout=self._timeout,
            )
            if response and response.generated_images:
                for gen_img in response.generated_images:
                    if gen_img.image and gen_img.image.image_bytes:
                        return gen_img.image.image_bytes
        else:
            config_opts = types.GenerateContentConfig(
                response_modalities=["IMAGE"],
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            )
            response = await asyncio.wait_for(
                self._client.aio.models.generate_content(
                    model=model_name,
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

    async def _generate_via_fallback(self, english_prompt: str, model: str = "flux-realism") -> bytes:
        """
        Генератор через открытые высокопроизводительные движки (Flux Realism / Flux / Turbo).
        """
        logger.info("[INFO] Используется фотореалистичный движок: %s", model)
        
        enhanced_prompt = f"{english_prompt}, sharp focus, photorealistic, 8k, detailed, professional photography, masterpiece"
        safe_prompt = aiohttp.helpers.quote(enhanced_prompt)
        seed = random.randint(1, 999999)
        
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        proxy_url = getattr(config, "PROXY_URL", None) or os.getenv("HTTP_PROXY") or None

        # Пробуем указанную модель (flux-realism / flux) с таймаутом 20с
        model_param = f"&model={model}" if model in ("flux-realism", "flux", "turbo") else "&model=flux-realism"
        url = f"https://image.pollinations.ai/prompt/{safe_prompt}?seed={seed}{model_param}&nologo=true"
        
        timeout = aiohttp.ClientTimeout(total=25)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            try:
                async with session.get(url, headers=headers, proxy=proxy_url) as resp:
                    if resp.status == 200:
                        raw_bytes = await resp.read()
                        if raw_bytes and len(raw_bytes) > 5000:
                            return self._remove_watermark(raw_bytes)
            except Exception as e:
                logger.info("[INFO] Запрос к %s завершился: %s, переключаемся на базовый поток...", model, e)

            # Быстрый резерв
            url_fast = f"https://image.pollinations.ai/prompt/{safe_prompt}?seed={seed}&nologo=true"
            fast_timeout = aiohttp.ClientTimeout(total=self._timeout)
            async with aiohttp.ClientSession(timeout=fast_timeout) as session_fast:
                async with session_fast.get(url_fast, headers=headers, proxy=proxy_url) as resp:
                    if resp.status != 200:
                        raise ImageGenerationError(f"HTTP ошибка генератора: {resp.status}")
                    raw_bytes = await resp.read()
                    if not raw_bytes:
                        raise ImageGenerationError("Генератор вернул пустые данные.")
                    return self._remove_watermark(raw_bytes)

    async def _generate_via_huggingface(self, english_prompt: str) -> bytes:
        """
        Генерация изображения через официальный Hugging Face Inference API (Stable Diffusion 3 Medium).
        Флагманская модель от Stability AI с фотореализмом и разрешением 1024x1024.
        """
        token = getattr(config, "HF_TOKEN", "") or os.getenv("HF_TOKEN", "")
        if not token:
            raise ImageGenerationError("HF_TOKEN не указан в файле .env")

        url = "https://router.huggingface.co/hf-inference/models/stabilityai/stable-diffusion-3-medium-diffusers"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "TelegramBot/1.0"
        }
        payload = {
            "inputs": english_prompt
        }
        timeout = aiohttp.ClientTimeout(total=50)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status == 200:
                    raw_bytes = await resp.read()
                    if raw_bytes and len(raw_bytes) > 5000:
                        return raw_bytes
                
                # Обработка лимитов и прогрева модели Hugging Face
                retry_after = resp.headers.get("Retry-After")
                error_body = ""
                estimated_time = None
                try:
                    data = await resp.json()
                    error_body = data.get("error", "")
                    estimated_time = data.get("estimated_time")
                except Exception:
                    try:
                        error_body = await resp.text()
                    except Exception:
                        pass

                if estimated_time:
                    raise ImageQuotaError(
                        f"⏳ <b>Модель сейчас подготавливается на сервере Hugging Face.</b>\n\n"
                        f"Примерное время ожидания: ~<b>{int(estimated_time)} сек.</b>\n"
                        f"Пожалуйста, подождите полминуты и повторите отправку запроса."
                    )

                if resp.status == 429:
                    wait_hint = f" ~{retry_after} сек." if retry_after else " 1–2 минуты"
                    raise ImageQuotaError(
                        f"⏳ <b>Лимит запросов к нейросети временно исчерпан.</b>\n\n"
                        f"Пожалуйста, подождите{wait_hint} и повторите попытку.\n\n"
                        f"<i>Частотный лимит сбрасывается каждую минуту, а суточная квота — в 00:00 UTC.</i>"
                    )

                if resp.status == 503:
                    raise ImageQuotaError(
                        "⏳ <b>Сервер генерации сейчас сильно загружен.</b>\n\n"
                        "Пожалуйста, подождите 30–60 секунд и повторите отправку запроса."
                    )

                raise ImageGenerationError(f"Hugging Face HTTP {resp.status}: {error_body[:200]}")

    async def generate_image(self, prompt: str) -> Tuple[bytes, str, bool]:
        """
        Главный метод генерации изображения.
        Возвращает кортеж: (image_bytes, used_model_name, is_fallback_boolean).
        """
        current_model = database.get_image_model()
        logger.info("[INFO] Image generation started. Model: '%s', Prompt: '%s'", current_model, prompt[:60])
        
        # 1. Переводим промпт на детальный английский через Gemini
        english_prompt = await self._translate_prompt(prompt)

        # 2. Если выбрана модель Hugging Face (Stable Diffusion 3)
        if current_model in ("hf-sd3", "hf-flux"):
            hf_bytes = await self._generate_via_huggingface(english_prompt)
            return hf_bytes, "Stable Diffusion 3 (HF)", False

        # 3. Если выбрана модель Google Gemini / Pro / Imagen
        is_google_model = any(k in current_model.lower() for k in ["gemini", "banana", "imagen"])
        if is_google_model:
            try:
                image_bytes = await self._generate_via_gemini(current_model, english_prompt)
                if image_bytes:
                    logger.info("[INFO] Image generated successfully via Google model: %s", current_model)
                    return image_bytes, current_model, False
                logger.warning("[WARNING] Google модель %s не вернула изображение.", current_model)
            except errors.ClientError as ce:
                if ce.code == 429 and "limit: 0" in str(ce):
                    raise ImageQuotaError(
                        f"❌ <b>Модель Google '{current_model}' заблокирована на бесплатном ключе.</b>\n\n"
                        "Google AI Studio требует подключить карту (Billing) для генерации изображений.\n\n"
                        "💡 <i>В панели /admin переключите модель на «Stable Diffusion 3 (Hugging Face)» — "
                        "она бесплатна, работает без карты и генерирует в высоком качестве 1024x1024.</i>"
                    )
                raise ImageGenerationError(f"Ошибка Google Image API: {ce.message}")
            except Exception as e:
                logger.warning("[WARNING] Ошибка обращения к Google Image API: %s", e)
                raise ImageGenerationError(f"Ошибка Google Image API: {e}")

        # 4. Если выбрана модель открытого семейства
        fallback_bytes = await self._generate_via_fallback(english_prompt, model=current_model)
        return fallback_bytes, current_model, False
