import os
import sys
from dotenv import load_dotenv

# Загружаем переменные окружения из файла .env
load_dotenv()

# Токен Telegram-бота
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "").strip()

# API-ключ Google Gemini
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "").strip()

# Модели Gemini
# gemini-3.5-flash — основная быстрая текстовая модель последнего поколения
# gemini-3.5-flash-lite — резервная легковесная модель с высокой квотой
GEMINI_TEXT_MODEL: str = os.getenv("GEMINI_TEXT_MODEL", "gemini-3.5-flash").strip()
GEMINI_FALLBACK_TEXT_MODEL: str = os.getenv("GEMINI_FALLBACK_TEXT_MODEL", "gemini-3.5-flash-lite").strip()

# Модель для генерации изображений через Google Imagen 3 (флагманская модель Google)
GEMINI_IMAGE_MODEL: str = os.getenv("GEMINI_IMAGE_MODEL", "imagen-3.0-generate-002").strip()

# Токен Hugging Face для бесплатной генерации FLUX.1
HF_TOKEN: str = os.getenv("HF_TOKEN", "").strip()

# Включение бесплатного fallback-генератора изображений (на случай лимита limit: 0 в Free Tier Google)
ENABLE_FREE_IMAGE_FALLBACK: bool = os.getenv("ENABLE_FREE_IMAGE_FALLBACK", "true").lower() in ("true", "1", "yes")

# Таймаут на запросы к AI в секундах
REQUEST_TIMEOUT: int = int(os.getenv("REQUEST_TIMEOUT", "60"))

# Максимальная длина сообщения Telegram (лимит Telegram 4096 символов)
MAX_MESSAGE_LENGTH: int = 4000

# Список ID администраторов (по умолчанию ваши ID: 8680736889 и 1915644408)
ADMIN_IDS_RAW: str = os.getenv("ADMIN_IDS", os.getenv("ADMIN_ID", "8680736889,1915644408")).strip()
ADMIN_IDS: list[int] = []
if ADMIN_IDS_RAW:
    for item in ADMIN_IDS_RAW.replace(";", ",").replace(" ", ",").split(","):
        item = item.strip()
        if item.isdigit():
            ADMIN_IDS.append(int(item))

# Валидация обязательных конфигурационных параметров
def validate_config() -> None:
    errors = []
    if not BOT_TOKEN or BOT_TOKEN.startswith("your_") or "TOKEN" in BOT_TOKEN:
        errors.append("BOT_TOKEN не задан или содержит шаблонное значение в файле .env")
    if not GEMINI_API_KEY or GEMINI_API_KEY.startswith("your_") or "KEY" in GEMINI_API_KEY:
        errors.append("GEMINI_API_KEY не задан или содержит шаблонное значение в файле .env")
    
    if errors:
        sys.stderr.write("\n[CRITICAL ERROR] Ошибка конфигурации:\n")
        for err in errors:
            sys.stderr.write(f"  - {err}\n")
        sys.stderr.write("\nСоздайте файл .env на основе .env.example и укажите реальные ключи.\n\n")
        sys.exit(1)