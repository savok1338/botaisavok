from aiogram.fsm.state import State, StatesGroup

class UserMode(StatesGroup):
    """
    Состояния FSM пользователя.
    
    chat_mode — режим активного текстового диалога с Gemini.
    image_mode — режим ожидания промпта для генерации картинки.
    """
    chat_mode = State()
    image_mode = State()


class AdminStates(StatesGroup):
    """
    Состояния FSM для администратора.
    """
    waiting_for_system_prompt = State()
    waiting_for_broadcast_text = State()
    waiting_for_disabled_message = State()
