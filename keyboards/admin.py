from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import database


def get_admin_keyboard() -> InlineKeyboardMarkup:
    """Главная клавиатура панели управления администратора."""
    ai_status = database.is_ai_enabled()
    status_text = "🟢 ИИ: Включен" if ai_status else "🔴 ИИ: Отключен"
    
    keyboard = [
        [
            InlineKeyboardButton(text=status_text, callback_data="admin:toggle_ai")
        ],
        [
            InlineKeyboardButton(text="🎭 Роль ИИ (AGENTS)", callback_data="admin:role"),
            InlineKeyboardButton(text="📢 Рассылка", callback_data="admin:broadcast")
        ],
        [
            InlineKeyboardButton(text="✏️ Текст при отключении", callback_data="admin:disabled_msg"),
            InlineKeyboardButton(text="📊 Статистика", callback_data="admin:stats")
        ],
        [
            InlineKeyboardButton(text="❌ Закрыть панель", callback_data="admin:close")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_admin_cancel_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура отмены текущего действия."""
    keyboard = [
        [
            InlineKeyboardButton(text="🔙 Отмена", callback_data="admin:cancel")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_role_actions_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура управления системным промптом."""
    keyboard = [
        [
            InlineKeyboardButton(text="✏️ Задать новую роль", callback_data="admin:set_prompt"),
            InlineKeyboardButton(text="🔄 Сбросить на стандартную", callback_data="admin:reset_prompt")
        ],
        [
            InlineKeyboardButton(text="🔙 Назад в меню", callback_data="admin:back_to_menu")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)
