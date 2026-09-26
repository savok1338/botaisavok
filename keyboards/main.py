from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

def get_main_keyboard() -> ReplyKeyboardMarkup:
    """
    Возвращает главное меню с кнопками режимов.
    """
    keyboard = [
        [
            KeyboardButton(text="🤖 Чат с ИИ"),
            KeyboardButton(text="🎨 Генерация изображения"),
        ],
        [
            KeyboardButton(text="ℹ️ Помощь"),
        ],
    ]
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        one_time_keyboard=False,
        input_field_placeholder="Выберите действие в меню...",
    )

def get_back_keyboard() -> ReplyKeyboardMarkup:
    """
    Возвращает клавиатуру с кнопкой возврата в главное меню.
    """
    keyboard = [
        [
            KeyboardButton(text="🔙 Назад"),
        ]
    ]
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        one_time_keyboard=False,
        input_field_placeholder="Введите сообщение или нажмите «Назад»...",
    )
