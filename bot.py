import asyncio
import logging
import os
import sys

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

import config
from handlers.start import router as start_router
from handlers.chat import router as chat_router
from handlers.image import router as image_router
from services.gemini import GeminiService
from services.image_generation import ImageGenerationService

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


async def start_healthcheck_server() -> None:
    """
    Легковесный HTTP-сервер для прохождения проверок (healthcheck)
    на облачных платформах (Hugging Face Spaces, Render и др.).
    """
    port = int(os.getenv("PORT", "7860"))
    app = web.Application()
    
    async def ping_handler(request: web.Request) -> web.Response:
        return web.Response(text="Bot is alive and running!", content_type="text/plain")

    app.router.add_get("/", ping_handler)
    app.router.add_get("/health", ping_handler)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()
    logger.info("[INFO] Healthcheck HTTP server started on port %d", port)


async def main() -> None:
    """
    Главная точка входа для инициализации и запуска бота.
    """
    config.validate_config()

    # Инициализация сессии с прокси (для PythonAnywhere и других прокси-сред)
    bot_session = None
    proxy_url = getattr(config, "PROXY_URL", "") or os.getenv("HTTP_PROXY") or os.getenv("http_proxy")
    if not proxy_url and (os.getenv("PYTHONANYWHERE_SITE") or os.getenv("PYTHONANYWHERE_DOMAIN") or os.path.exists("/home/savok88") or os.path.isdir("/var/www")):
        proxy_url = "http://proxy.server:3128"

    if proxy_url:
        bot_session = AiohttpSession(proxy=proxy_url)
        logger.info("[INFO] Используется HTTP-прокси для Telegram: %s", proxy_url)

    bot = Bot(
        token=config.BOT_TOKEN,
        session=bot_session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    dp = Dispatcher(storage=MemoryStorage())

    gemini_service = GeminiService()
    image_service = ImageGenerationService()

    dp["gemini_service"] = gemini_service
    dp["image_service"] = image_service

    dp.include_router(start_router)
    dp.include_router(chat_router)
    dp.include_router(image_router)

    # Запускаем HTTP healthcheck для облачных платформ
    try:
        await start_healthcheck_server()
    except Exception as srv_err:
        logger.warning("[WARNING] Не удалось запустить healthcheck-сервер: %s", srv_err)

    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        logger.warning("[WARNING] Не удалось сбросить webhook: %s", e)

    logger.info("[INFO] Bot started")
    logger.info("[INFO] Используемая модель текста: %s", config.GEMINI_TEXT_MODEL)
    logger.info("[INFO] Резервная модель текста: %s", config.GEMINI_FALLBACK_TEXT_MODEL)
    logger.info("[INFO] Модель генерации изображений: %s", config.GEMINI_IMAGE_MODEL)

    try:
        await dp.start_polling(bot)
    finally:
        logger.info("[INFO] Завершение работы бота...")
        await bot.session.close()
        logger.info("[INFO] Сессия бота закрыта")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("[INFO] Бот остановлен пользователем")
