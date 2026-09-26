import asyncio
import logging
from aiogram import Router, F, Bot
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

import config
import database
from keyboards.main import get_back_keyboard
from services.gemini import GeminiService
from states import UserMode
from utils.text_splitter import split_text

logger = logging.getLogger(__name__)

router = Router(name="chat_router")


@router.message(F.text == "🤖 Чат с ИИ")
async def enter_chat_mode(message: Message, state: FSMContext) -> None:
    """
    Переводит пользователя в режим текстового диалога с Gemini.
    """
    # Сохраняем пользователя в базу
    database.add_user(
        user_id=message.from_user.id if message.from_user else 0,
        username=message.from_user.username if message.from_user else None,
        first_name=message.from_user.first_name if message.from_user else None
    )

    if not database.is_ai_enabled():
        await message.answer(database.get_disabled_message())
        return

    await state.set_state(UserMode.chat_mode)
    user_id = message.from_user.id if message.from_user else 0
    logger.info("[INFO] User %d switched to chat mode", user_id)
    
    await message.answer(
        "Режим чата включён. 🤖\n\n"
        "Напишите ваше сообщение, и Gemini ответит вам.\n"
        "Контекст диалога сохраняется. Для завершения нажмите «🔙 Назад».",
        reply_markup=get_back_keyboard()
    )


@router.message(UserMode.chat_mode, F.text)
async def process_chat_message(
    message: Message,
    bot: Bot,
    gemini_service: GeminiService
) -> None:
    """
    Обрабатывает текстовые сообщения пользователя в режиме диалога.
    """
    user_text = message.text.strip() if message.text else ""
    user_id = message.from_user.id if message.from_user else 0

    # Пропуск системных команд или пустых сообщений
    if not user_text:
        await message.answer("Пожалуйста, введите текстовое сообщение.")
        return

    if user_text.startswith("/"):
        return

    # Проверка, включен ли ИИ администратором
    if not database.is_ai_enabled():
        await message.answer(database.get_disabled_message())
        return

    # Проверка на превышение длины входного сообщения
    if len(user_text) > config.MAX_MESSAGE_LENGTH:
        await message.answer(
            f"⚠️ Ваше сообщение слишком длинное ({len(user_text)} символов).\n"
            f"Пожалуйста, сократите запрос до {config.MAX_MESSAGE_LENGTH} символов."
        )
        return

    logger.info("[INFO] User %d sent message", user_id)

    # Показываем индикатор набора текста Telegram
    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)

    # Отправляем сообщение-индикатор ожидания
    status_msg = await message.answer("🤖 Думаю...")

    # Фоновая задача для продления индикатора typing при долгих ответах
    async def keep_typing() -> None:
        try:
            while True:
                await asyncio.sleep(4.5)
                await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)
        except asyncio.CancelledError:
            pass

    typing_task = asyncio.create_task(keep_typing())

    try:
        # Запрос к Gemini Service
        response_text = await gemini_service.generate_text(user_id=user_id, prompt=user_text)
        
        # Удаляем сообщение со статусом «🤖 Думаю...»
        try:
            await status_msg.delete()
        except TelegramBadRequest:
            pass

        # Разбиваем длинный ответ на части (лимит 4096 символов Telegram)
        chunks = split_text(response_text, max_chunk_size=config.MAX_MESSAGE_LENGTH)
        
        for chunk in chunks:
            try:
                # Сначала пробуем отправить как Markdown
                await message.answer(chunk, parse_mode="Markdown")
            except TelegramBadRequest:
                # Если в ответе ИИ есть незакрытые спецсимволы Markdown, отправляем обычным текстом
                await message.answer(chunk)
                
    except Exception as exc:
        logger.error("[ERROR] Gemini API error: %s", exc)
        try:
            await status_msg.delete()
        except TelegramBadRequest:
            pass
        await message.answer("Произошла ошибка при обращении к AI. Попробуйте ещё раз.")
        
    finally:
        typing_task.cancel()
