import asyncio
import logging
from aiogram import Router, F, Bot
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, BufferedInputFile

import database
from keyboards.main import get_back_keyboard
from services.image_generation import ImageGenerationService, ImageQuotaError
from states import UserMode

logger = logging.getLogger(__name__)

router = Router(name="image_router")


@router.message(F.text == "🎨 Генерация изображения")
async def enter_image_mode(message: Message, state: FSMContext) -> None:
    """
    Переводит пользователя в режим генерации изображений.
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

    await state.set_state(UserMode.image_mode)
    user_id = message.from_user.id if message.from_user else 0
    logger.info("[INFO] User %d switched to image generation mode", user_id)
    
    await message.answer(
        "Режим генерации изображений включён. 🎨\n\n"
        "Опишите изображение, которое хотите создать.\n\n"
        "<i>Например:</i>\n"
        "<code>Фотореалистичный ночной город под дождём, снятый на объектив камеры наблюдения</code>\n\n"
        "Для отмены или выхода в меню нажмите кнопку «🔙 Назад».",
        reply_markup=get_back_keyboard(),
        parse_mode="HTML"
    )


@router.message(UserMode.image_mode, F.text)
async def process_image_prompt(
    message: Message,
    bot: Bot,
    image_service: ImageGenerationService
) -> None:
    """
    Обрабатывает текстовый запрос на генерацию картинки.
    """
    prompt = message.text.strip() if message.text else ""
    user_id = message.from_user.id if message.from_user else 0

    if not prompt:
        await message.answer("Пожалуйста, опишите изображение текстом.")
        return

    if prompt.startswith("/"):
        return

    # Проверка, включен ли ИИ администратором
    if not database.is_ai_enabled():
        await message.answer(database.get_disabled_message())
        return

    logger.info("[INFO] Image generation started for user_id=%d", user_id)

    # Показываем статус отправки фото
    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.UPLOAD_PHOTO)

    # Индикатор генерации изображения
    status_msg = await message.answer("🎨 Создаю изображение...")

    # Фоновая поддержка индикатора UPLOAD_PHOTO
    async def keep_uploading() -> None:
        try:
            while True:
                await asyncio.sleep(4.5)
                await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.UPLOAD_PHOTO)
        except asyncio.CancelledError:
            pass

    action_task = asyncio.create_task(keep_uploading())

    try:
        # Вызов сервиса генерации
        image_bytes, used_model, is_fallback = await image_service.generate_image(prompt)
        
        # Удаляем сообщение со статусом
        try:
            await status_msg.delete()
        except TelegramBadRequest:
            pass

        # Подготовка файла из памяти и отправка в Telegram
        photo_file = BufferedInputFile(file=image_bytes, filename="generated_image.png")
        
        caption_lines = [
            "✨ <b>Результат по вашему описанию:</b>",
            f"<i>{prompt[:250]}</i>",
            "",
            f"🎯 <b>Модель:</b> <code>{used_model}</code>"
        ]
        if is_fallback:
            caption_lines.append("ℹ️ <i>(В Google AI Studio лимит 0, использован резерв Flux Realism)</i>")

        caption_text = "\n".join(caption_lines)
        
        await message.answer_photo(
            photo=photo_file,
            caption=caption_text,
            parse_mode="HTML"
        )
        logger.info("[INFO] Photo successfully sent to user_id=%d (model=%s)", user_id, used_model)

    except ImageQuotaError as quota_err:
        logger.warning("[WARNING] Quota error during image generation: %s", quota_err)
        try:
            await status_msg.delete()
        except TelegramBadRequest:
            pass
        await message.answer(
            f"ℹ️ {quota_err}\n\n"
            "Вы можете продолжить общение в режиме «🤖 Чат с ИИ»."
        )

    except Exception as exc:
        logger.error("[ERROR] Image generation error: %s", exc)
        try:
            await status_msg.delete()
        except TelegramBadRequest:
            pass
        await message.answer(
            "Произошла ошибка при создании изображения. "
            "Попробуйте переформулировать запрос или повторите попытку позже."
        )

    finally:
        action_task.cancel()
