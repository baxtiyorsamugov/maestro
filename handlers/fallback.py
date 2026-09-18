"""
Ответ на всё, что не подошло ни одному хендлеру.

Роутер подключается последним: в aiogram роутер сначала проверяет свои
хендлеры, потом дочерние, поэтому catch-all в любом другом месте
перехватил бы вообще всё.
"""

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    Message,
)

from guards import (
    get_user_lang,
)
from keyboards import (
    get_main_keyboard,
)

router = Router(name="fallback")


@router.message()
async def fallback_message(message: Message, state: FSMContext):
    """
    Всё, что не подошло ни одному хендлеру выше. Без этого бот молчит
    в ответ на произвольный текст, и пользователь не понимает, что делать.
    """
    if await state.get_state() is not None:
        # Мы внутри сценария — подсказываем, что ожидается, и не сбрасываем состояние.
        lang = await get_user_lang(message.from_user.id)
        await message.answer(
            {
                "ru": "Не понял ответ. Воспользуйтесь кнопками выше или отправьте /start, чтобы начать заново.",
                "uz": "Javobni tushunmadim. Yuqoridagi tugmalardan foydalaning yoki qaytadan boshlash uchun /start yuboring.",
            }[lang]
        )
        return

    lang = await get_user_lang(message.from_user.id)
    await message.answer(
        {
            "ru": "Я понимаю только кнопки меню. Выберите действие ниже.",
            "uz": "Men faqat menyu tugmalarini tushunaman. Quyidan amalni tanlang.",
        }[lang],
        reply_markup=await get_main_keyboard(message.from_user.id),
    )
