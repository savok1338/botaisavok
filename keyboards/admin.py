from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import database

# Доступные проверенные модели текста
AVAILABLE_TEXT_MODELS = [
    ("gemini-3.8-flash", "⚡ Gemini 3.8 Flash (Новейшая)"),
    ("gemini-3.7-flash", "🧠 Gemini 3.7 Flash (Логика и рассуждения)"),
    ("gemini-3.6-flash", "💎 Gemini 3.6 Flash (Стабильная)"),
    ("gemini-3.5-flash-lite", "🚀 Gemini 3.5 Flash Lite (Супер-квота)"),
    ("gemini-3-flash-preview", "🧪 Gemini 3 Flash Preview (Тестовая)")
]

# Доступные проверенные модели генерации картинок
AVAILABLE_IMAGE_MODELS = [
    ("nano-banana-pro-preview", "🍌 Nano-Banana Pro (Google Pro)"),
    ("gemini-3-pro-image", "🌟 Gemini 3 Pro Image (Google Pro)"),
    ("gemini-3.1-flash-image", "⚡ Gemini 3.1 Flash Image (Google)"),
    ("imagen-3.0-generate-002", "🎨 Google Imagen 3"),
    ("flux-realism", "📸 Flux Realism (Фотореализм 8K)"),
    ("flux", "🖌️ Flux 12B (Художественный)"),
    ("turbo", "⚡ Turbo SDXL (Быстрый)")
]


def get_admin_keyboard() -> InlineKeyboardMarkup:
    """Главная клавиатура панели управления администратора."""
    ai_status = database.is_ai_enabled()
    status_text = "🟢 ИИ: Включен" if ai_status else "🔴 ИИ: Отключен"
    
    keyboard = [
        [
            InlineKeyboardButton(text=status_text, callback_data="admin:toggle_ai")
        ],
        [
            InlineKeyboardButton(text="🧠 Модель текста", callback_data="admin:text_models"),
            InlineKeyboardButton(text="🎨 Модель картинок", callback_data="admin:image_models")
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


def get_text_models_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора модели текстового ИИ."""
    current = database.get_text_model()
    buttons = []
    for model_id, label in AVAILABLE_TEXT_MODELS:
        prefix = "✅ " if model_id == current else ""
        buttons.append([
            InlineKeyboardButton(
                text=f"{prefix}{label}",
                callback_data=f"admin:set_tm:{model_id}"
            )
        ])
    buttons.append([
        InlineKeyboardButton(text="🔙 Назад в меню", callback_data="admin:back_to_menu")
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_image_models_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора модели генерации картинок."""
    current = database.get_image_model()
    buttons = []
    for model_id, label in AVAILABLE_IMAGE_MODELS:
        prefix = "✅ " if model_id == current else ""
        buttons.append([
            InlineKeyboardButton(
                text=f"{prefix}{label}",
                callback_data=f"admin:set_im:{model_id}"
            )
        ])
    buttons.append([
        InlineKeyboardButton(text="🔙 Назад в меню", callback_data="admin:back_to_menu")
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


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
