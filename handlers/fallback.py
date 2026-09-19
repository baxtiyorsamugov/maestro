"""
Ответ на всё, что не подошло ни одному хендлеру.

Роутер подключается последним: в aiogram роутер сначала проверяет свои
хендлеры, потом дочерние, поэтому catch-all в любом другом месте
перехватил бы вообще всё.
"""

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import texts
from guards import get_user_lang
from keyboards import get_main_keyboard

router = Router(name="fallback")


@router.message()
async def fallback_message(message: Message, state: FSMContext):
    """
    Всё, что не подошло ни одному хендлеру выше. Без этого бот молчит
    в ответ на произвольный текст, и пользователь не понимает, что делать.
    """
    lang = await get_user_lang(message.from_user.id)

    if await state.get_state() is not None:
        # Мы внутри сценария — подсказываем, что ожидается, и не сбрасываем состояние.
        await message.answer(texts.get_text("fallback_in_scenario", lang))
        return

    await message.answer(
        texts.get_text("fallback_use_menu", lang),
        reply_markup=await get_main_keyboard(message.from_user.id),
    )


@router.callback_query()
async def fallback_callback(cb: CallbackQuery):
    """
    Нажатие на кнопку, которую никто не обработал.

    Так выглядит кнопка из старого сообщения после того, как формат
    callback_data изменился: в чате она осталась, а хендлера под неё уже нет.
    Без этого хендлера в клиенте просто висят «часики» — пользователь не понимает,
    сломался бот или он сам сделал что-то не так.
    """
    lang = await get_user_lang(cb.from_user.id)
    await cb.answer(texts.get_text("fallback_button_outdated", lang), show_alert=True)

    # Меню возвращаем отдельным сообщением: старое трогать нельзя, оно может
    # быть частью медиагруппы или уже удалено.
    if cb.message:
        await cb.message.answer(
            texts.get_text("fallback_use_menu", lang),
            reply_markup=await get_main_keyboard(cb.from_user.id),
        )
