import asyncio
import logging
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

import config
import database
from keyboards.admin import (
    get_admin_keyboard,
    get_admin_cancel_keyboard,
    get_role_actions_keyboard,
)
from states import AdminStates

logger = logging.getLogger(__name__)

router = Router(name="admin_router")


def is_admin(user_id: int) -> bool:
    """Проверка прав администратора."""
    # Если список ADMIN_IDS пуст, доступ временно открыт для настройки, с предупреждением
    if not config.ADMIN_IDS:
        return True
    return user_id in config.ADMIN_IDS


def format_admin_menu_text() -> str:
    """Форматирование главного текста админ-панели."""
    ai_status = "🟢 <b>ВКЛЮЧЕН</b>" if database.is_ai_enabled() else "🔴 <b>ОТКЛЮЧЕН</b>"
    users_cnt = database.get_users_count()
    current_prompt = database.get_system_prompt()
    if len(current_prompt) > 120:
        current_prompt = current_prompt[:120] + "..."
    disabled_text = database.get_disabled_message()

    return (
        "⚙️ <b>Панель управления администратора</b>\n\n"
        f"• <b>Статус работы ИИ:</b> {ai_status}\n"
        f"• <b>Пользователей в базе:</b> {users_cnt}\n"
        f"• <b>Текст заглушки при выключении:</b>\n<i>{disabled_text}</i>\n\n"
        f"• <b>Текущая роль (AGENTS):</b>\n<code>{current_prompt}</code>\n\n"
        "Выберите действие в меню ниже 👇"
    )


@router.message(Command("myid"))
async def handle_myid(message: Message) -> None:
    """Показывает пользователю его Telegram ID."""
    user_id = message.from_user.id if message.from_user else 0
    await message.answer(
        f"Ваш Telegram ID: <code>{user_id}</code>\n"
        "Добавьте его в <code>ADMIN_ID=...</code> в файле .env для доступа к админ-панели.",
        parse_mode="HTML"
    )


@router.message(Command("admin"))
async def handle_admin_command(message: Message, state: FSMContext) -> None:
    """Вход в админ-панель по команде /admin."""
    await state.clear()
    user_id = message.from_user.id if message.from_user else 0

    if not is_admin(user_id):
        await message.answer("⛔ У вас нет доступа к панели администратора.")
        return

    logger.info("[INFO] Admin %d opened admin panel", user_id)
    await message.answer(
        format_admin_menu_text(),
        reply_markup=get_admin_keyboard(),
        parse_mode="HTML"
    )


# -------------------------------------------------------------
# Callbacks управления админ-панелью
# -------------------------------------------------------------

@router.callback_query(F.data == "admin:toggle_ai")
async def callback_toggle_ai(call: CallbackQuery) -> None:
    """Переключение статуса работы ИИ (вкл / выкл)."""
    if not is_admin(call.from_user.id):
        await call.answer("Доступ запрещен", show_alert=True)
        return

    new_status = not database.is_ai_enabled()
    database.set_ai_enabled(new_status)
    logger.info("[INFO] Admin %d changed AI status to: %s", call.from_user.id, new_status)
    
    await call.answer("Статус ИИ изменен!")
    try:
        await call.message.edit_text(
            format_admin_menu_text(),
            reply_markup=get_admin_keyboard(),
            parse_mode="HTML"
        )
    except Exception:
        pass


@router.callback_query(F.data == "admin:role")
async def callback_role_menu(call: CallbackQuery) -> None:
    """Меню управления системным промптом (AGENTS)."""
    if not is_admin(call.from_user.id):
        await call.answer("Доступ запрещен", show_alert=True)
        return

    prompt_text = database.get_system_prompt()
    text = (
        "🎭 <b>Управление ролью и поведением ИИ (AGENTS)</b>\n\n"
        "Системный промпт определяет характер, стиль и правила ответов Gemini для всех пользователей.\n\n"
        f"<b>Текущий системный промпт:</b>\n"
        f"<code>{prompt_text}</code>"
    )
    await call.message.edit_text(text, reply_markup=get_role_actions_keyboard(), parse_mode="HTML")


@router.callback_query(F.data == "admin:set_prompt")
async def callback_set_prompt_start(call: CallbackQuery, state: FSMContext) -> None:
    """Начало ввода нового системного промпта."""
    if not is_admin(call.from_user.id):
        return
    await state.set_state(AdminStates.waiting_for_system_prompt)
    await call.message.edit_text(
        "📝 <b>Введите новую роль / системный промпт:</b>\n\n"
        "<i>Например:</i>\n"
        "<code>Ты — дерзкий программист-эксперт. Отвечай кратко, саркастично, но строго по делу и с идеальным кодом.</code>",
        reply_markup=get_admin_cancel_keyboard(),
        parse_mode="HTML"
    )


@router.message(AdminStates.waiting_for_system_prompt, F.text)
async def process_new_system_prompt(message: Message, state: FSMContext) -> None:
    """Сохранение нового системного промпта."""
    if not is_admin(message.from_user.id):
        return

    new_prompt = message.text.strip()
    database.set_system_prompt(new_prompt)
    await state.clear()
    logger.info("[INFO] Admin %d updated system prompt", message.from_user.id)

    await message.answer("✅ <b>Роль ИИ успешно обновлена!</b>", parse_mode="HTML")
    await message.answer(
        format_admin_menu_text(),
        reply_markup=get_admin_keyboard(),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "admin:reset_prompt")
async def callback_reset_prompt(call: CallbackQuery) -> None:
    """Сброс системного промпта к дефолтному."""
    if not is_admin(call.from_user.id):
        return
    database.set_system_prompt(database.DEFAULT_SYSTEM_PROMPT)
    await call.answer("Роль сброшена на стандартную!")
    await call.message.edit_text(
        format_admin_menu_text(),
        reply_markup=get_admin_keyboard(),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "admin:disabled_msg")
async def callback_set_disabled_msg(call: CallbackQuery, state: FSMContext) -> None:
    """Начало изменения текста заглушки при выключенном ИИ."""
    if not is_admin(call.from_user.id):
        return
    await state.set_state(AdminStates.waiting_for_disabled_message)
    current = database.get_disabled_message()
    await call.message.edit_text(
        "✏️ <b>Введите текст, который увидят пользователи при отключении ИИ:</b>\n\n"
        f"<i>Текущий текст:</i> <code>{current}</code>",
        reply_markup=get_admin_cancel_keyboard(),
        parse_mode="HTML"
    )


@router.message(AdminStates.waiting_for_disabled_message, F.text)
async def process_new_disabled_msg(message: Message, state: FSMContext) -> None:
    """Сохранение нового текста заглушки."""
    if not is_admin(message.from_user.id):
        return

    new_msg = message.text.strip()
    database.set_disabled_message(new_msg)
    await state.clear()
    logger.info("[INFO] Admin %d updated disabled message", message.from_user.id)

    await message.answer("✅ <b>Текст заглушки успешно сохранён!</b>", parse_mode="HTML")
    await message.answer(
        format_admin_menu_text(),
        reply_markup=get_admin_keyboard(),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "admin:broadcast")
async def callback_broadcast_start(call: CallbackQuery, state: FSMContext) -> None:
    """Начало создания рассылки."""
    if not is_admin(call.from_user.id):
        return
    await state.set_state(AdminStates.waiting_for_broadcast_text)
    users_cnt = database.get_users_count()
    await call.message.edit_text(
        f"📢 <b>Массовая рассылка сообщений</b>\n\n"
        f"Получателей в базе: <b>{users_cnt}</b> чел.\n\n"
        "Отправьте текст (или текст с картинкой), который хотите разослать:",
        reply_markup=get_admin_cancel_keyboard(),
        parse_mode="HTML"
    )


@router.message(AdminStates.waiting_for_broadcast_text)
async def process_broadcast_message(message: Message, state: FSMContext, bot: Bot) -> None:
    """Выполнение рассылки всем пользователям."""
    if not is_admin(message.from_user.id):
        return

    await state.clear()
    user_ids = database.get_all_user_ids()
    total = len(user_ids)
    
    if total == 0:
        await message.answer("В базе еще нет пользователей для рассылки.")
        return

    status_msg = await message.answer(f"⏳ Рассылка запущена для {total} пользователей...")

    success = 0
    fail = 0

    for uid in user_ids:
        try:
            # Копируем сообщение пользователю со всеми медиа и форматированием
            await message.copy_to(chat_id=uid)
            success += 1
            await asyncio.sleep(0.05)  # Защита от лимитов Telegram (30 сообщений в секунду)
        except Exception as e:
            fail += 1
            logger.warning("[WARNING] Не удалось доставить рассылку user_id=%d: %s", uid, e)

    await status_msg.edit_text(
        f"✅ <b>Рассылка завершена!</b>\n\n"
        f"• Всего пользователей: {total}\n"
        f"• Успешно доставлено: {success}\n"
        f"• Не доставлено (заблокировали бота): {fail}",
        parse_mode="HTML"
    )
    await message.answer(
        format_admin_menu_text(),
        reply_markup=get_admin_keyboard(),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "admin:stats")
async def callback_stats(call: CallbackQuery) -> None:
    """Показать статистику."""
    if not is_admin(call.from_user.id):
        return
    count = database.get_users_count()
    await call.answer(f"Всего пользователей в базе: {count}", show_alert=True)


@router.callback_query(F.data == "admin:back_to_menu")
async def callback_back_menu(call: CallbackQuery, state: FSMContext) -> None:
    """Возврат в главное меню админки."""
    await state.clear()
    await call.message.edit_text(
        format_admin_menu_text(),
        reply_markup=get_admin_keyboard(),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "admin:cancel")
async def callback_cancel(call: CallbackQuery, state: FSMContext) -> None:
    """Отмена текущего действия."""
    await state.clear()
    await call.answer("Действие отменено")
    await call.message.edit_text(
        format_admin_menu_text(),
        reply_markup=get_admin_keyboard(),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "admin:close")
async def callback_close(call: CallbackQuery, state: FSMContext) -> None:
    """Закрыть админ-панель."""
    await state.clear()
    await call.message.delete()
