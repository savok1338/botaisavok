from aiogram.fsm.state import State, StatesGroup

class UserMode(StatesGroup):
    """
    Состояния FSM пользователя.
    
    chat_mode — режим активного текстового диалога с Gemini.
    image_mode — режим ожидания промпта для генерации картинки.
    """
    chat_mode = State()
    image_mode = State()
