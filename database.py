import sqlite3
import os
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "bot.db")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Инициализация таблиц базы данных."""
    with get_connection() as conn:
        cursor = conn.cursor()
        # Таблица пользователей для рассылок и статистики
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Таблица настроек бота (статус ИИ, роль, тексты)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        conn.commit()
    logger.info("[INFO] База данных SQLite инициализирована: %s", DB_PATH)


def add_user(user_id: int, username: Optional[str] = None, first_name: Optional[str] = None) -> None:
    """Добавить или обновить пользователя в базе."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO users (user_id, username, first_name)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name
        """, (user_id, username, first_name))
        conn.commit()


def get_all_user_ids() -> List[int]:
    """Получить список всех ID пользователей для рассылки."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users")
        rows = cursor.fetchall()
        return [row["user_id"] for row in rows]


def get_users_count() -> int:
    """Получить общее количество пользователей."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as count FROM users")
        row = cursor.fetchone()
        return row["count"] if row else 0


def get_setting(key: str, default: str = "") -> str:
    """Получить значение настройки из БД."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    """Сохранить значение настройки в БД."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO settings (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """, (key, value))
        conn.commit()


# Удобные хелперы для основных настроек
def is_ai_enabled() -> bool:
    """Проверка, включен ли ИИ."""
    val = get_setting("ai_enabled", "true").lower()
    return val in ("true", "1", "yes")


def set_ai_enabled(enabled: bool) -> None:
    """Включить или отключить ИИ."""
    set_setting("ai_enabled", "true" if enabled else "false")


DEFAULT_SYSTEM_PROMPT = (
    "Ты — умный, доброжелательный и высококвалифицированный персональный ассистент. "
    "Отвечай емко, по делу и структурированно."
)


def get_system_prompt() -> str:
    """Получить текущую роль / системную инструкцию ИИ."""
    return get_setting("system_prompt", DEFAULT_SYSTEM_PROMPT)


def set_system_prompt(prompt: str) -> None:
    """Установить новую роль / системную инструкцию ИИ."""
    set_setting("system_prompt", prompt.strip())


def get_disabled_message() -> str:
    """Сообщение, когда работа ИИ отключена."""
    return get_setting("disabled_message", "Работа ИИ отключена, писать @claude5opus")


def set_disabled_message(msg: str) -> None:
    """Установить сообщение при отключенном ИИ."""
    set_setting("disabled_message", msg.strip())


def get_text_model() -> str:
    """Получить выбранную модель для текстового ИИ."""
    import config
    return get_setting("text_model", config.GEMINI_TEXT_MODEL)


def set_text_model(model_name: str) -> None:
    """Установить выбранную модель для текстового ИИ."""
    set_setting("text_model", model_name.strip())


def get_image_model() -> str:
    """Получить выбранную модель для генерации изображений."""
    import config
    return get_setting("image_model", getattr(config, "GEMINI_IMAGE_MODEL", "hf-sd3"))


def set_image_model(model_name: str) -> None:
    """Установить выбранную модель для генерации изображений."""
    set_setting("image_model", model_name.strip())

