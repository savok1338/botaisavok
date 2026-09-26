import logging
from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from keyboards.main import get_main_keyboard
from services.gemini import GeminiService
import database

logger = logging.getLogger(__name__)

router = Router(name="start_router")


@router.message(CommandStart())
async def handle_start(message: Message, state: FSMContext) -> None:
    """
    Обработчик команды /start.
    Сбрасывает текущее состояние и показывает главное меню.
    """
    await state.clear()
    user_name = message.from_user.first_name if message.from_user else "друг"
    user_id = message.from_user.id if message.from_user else 0
    username = message.from_user.username if message.from_user else None
    
    # Сохраняем пользователя в базу для статистики и рассылок
    database.add_user(user_id=user_id, username=username, first_name=user_name)
    logger.info("[INFO] User %d executed /start", user_id)

    welcome_text = (
        f"👋 Привет, <b>{user_name}</b>!\n\n"
        "Я персональный Telegram-бот с искусственным интеллектом <b>Google Gemini</b>.\n\n"
        "<b>Доступные возможности:</b>\n"
        "🤖 <b>Чат с ИИ</b> — умный диалог с памятью контекста предыдущих сообщений\n"
        "🎨 <b>Генерация изображения</b> — создание иллюстраций по вашему описанию\n"
        "ℹ️ <b>Помощь</b> — подробная справка по боту\n\n"
        "<b>Команды:</b>\n"
        "/start — главное меню\n"
        "/help — помощь и инструкция\n"
        "/reset — сбросить контекст текущего диалога\n\n"
        "Выберите действие на клавиатуре ниже 👇"
    )
    await message.answer(welcome_text, reply_markup=get_main_keyboard(), parse_mode="HTML")


@router.message(Command("help"))
@router.message(F.text == "ℹ️ Помощь")
async def handle_help(message: Message) -> None:
    """
    Обработчик команды /help и кнопки «ℹ️ Помощь».
    """
    user_id = message.from_user.id if message.from_user else 0
    logger.info("[INFO] User %d asked for /help", user_id)

    help_text = (
        "📖 <b>Справка по использованию бота:</b>\n\n"
        "1️⃣ <b>Режим «🤖 Чат с ИИ»:</b>\n"
        "• Нажмите кнопку в меню и отправляйте любые сообщения.\n"
        "• Бот помнит историю сообщений в рамках диалога (например, ваше имя или детали задачи).\n"
        "• Длинные ответы автоматически разбиваются на несколько частей.\n\n"
        "2️⃣ <b>Очистка контекста (/reset):</b>\n"
        "• Если тема беседы сменилась, выполните команду /reset.\n"
        "• Это сотрет только вашу историю диалога, не затронув других пользователей.\n\n"
        "3️⃣ <b>Режим «🎨 Генерация изображения»:</b>\n"
        "• Перейдите в режим и подробно опишите, что хотите увидеть на картинке.\n"
        "• Можно писать как на русском, так и на английском.\n\n"
        "4️⃣ <b>Кнопка «🔙 Назад»:</b>\n"
        "• В любой момент возвращает вас в главное меню."
    )
    await message.answer(help_text, reply_markup=get_main_keyboard(), parse_mode="HTML")


@router.message(Command("reset"))
async def handle_reset(message: Message, gemini_service: GeminiService) -> None:
    """
    Обработчик команды /reset. Очищает память диалога только текущего пользователя.
    """
    user_id = message.from_user.id if message.from_user else 0
    gemini_service.reset_history(user_id)
    logger.info("[INFO] User %d cleared dialogue history via /reset", user_id)
    
    await message.answer(
        "🧹 <b>Память диалога очищена!</b>\n\n"
        "Gemini забыл предыдущую беседу. Теперь можно начать новый диалог с чистого листа.",
        parse_mode="HTML"
    )


@router.message(F.text == "🔙 Назад")
async def handle_back(message: Message, state: FSMContext) -> None:
    """
    Обработчик универсальной кнопки «🔙 Назад».
    Сбрасывает FSM-режим и возвращает в главное меню.
    """
    await state.clear()
    user_id = message.from_user.id if message.from_user else 0
    logger.info("[INFO] User %d returned to main menu", user_id)
    
    await message.answer(
        "Вы вернулись в главное меню. Выберите нужный режим:",
        reply_markup=get_main_keyboard()
    )
