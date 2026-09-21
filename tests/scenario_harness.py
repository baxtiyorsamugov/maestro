"""
Стенд для сквозных сценариев: апдейт идёт через настоящий диспетчер.

Раньше сценарии проверялись смоук-скриптами, которые вызывали функции
хендлеров напрямую. У этого два изъяна.

Первый — они обходили ровно то, где прячутся самые неприятные баги: порядок
роутеров, фильтры, FSM между шагами, middleware. Хендлер, до которого апдейт
никогда не доходит, потому что его перехватил соседний роутер, в таком
тесте работает прекрасно.

Второй — скрипты жили у меня во временной папке и в CI не попадали. Они
защищали ровно до тех пор, пока я запускал их руками.

Здесь апдейт уходит в `dp.feed_update()` — тот же путь, что у живого бота.
Подменяется только сессия: вместо Telegram запросы записываются в список,
по которому тест потом смотрит, что бот ответил.

Почему не библиотека aiogram-tests, названная в роадмапе: она проверяет
хендлеры по одному, в изоляции, — то есть обходит то же, что обходили
смоук-скрипты. Для сквозных сценариев это не подходит.
"""
from __future__ import annotations

import itertools
from datetime import datetime
from typing import Any

from aiogram.client.session.base import BaseSession
from aiogram.methods import TelegramMethod
from aiogram.types import (
    CallbackQuery,
    Chat,
    InlineKeyboardMarkup,
    Message,
    Update,
    User,
)

_ids = itertools.count(1)

BOT_USER = User(id=4242, is_bot=True, first_name="Maestro", username="maestro_test_bot")


def _fake_message(chat_id: int, text: str | None = None, reply_markup=None) -> Message:
    return Message(
        message_id=next(_ids),
        date=datetime.now(),
        chat=Chat(id=chat_id, type="private"),
        from_user=BOT_USER,
        text=text,
        reply_markup=reply_markup,
    )


class RecordingSession(BaseSession):
    """
    Сессия, которая никуда не ходит, а записывает запросы.

    Возвращает правдоподобные ответы по типу метода: код бота читает
    результат `message.answer()` и упал бы на None.
    """

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[TelegramMethod] = []

    async def make_request(self, bot, method: TelegramMethod, timeout: int | None = None) -> Any:
        self.calls.append(method)
        returning = str(method.__returning__)

        if "list" in returning:
            return [_fake_message(getattr(method, "chat_id", 0) or 0)]
        if "Message" in returning:
            return _fake_message(
                getattr(method, "chat_id", 0) or 0,
                getattr(method, "text", None) or getattr(method, "caption", None),
                getattr(method, "reply_markup", None),
            )
        if "User" in returning:
            return BOT_USER
        return True

    async def close(self) -> None:
        pass

    async def stream_content(self, *args, **kwargs):  # pragma: no cover - не нужен в сценариях
        if False:
            yield b""


class Replies:
    """Разбор того, что бот ответил на один апдейт."""

    #: Методы, которые что-то показывают человеку.
    VISIBLE = ("SendMessage", "EditMessageText", "SendPhoto", "EditMessageCaption")

    def __init__(self, calls: list[TelegramMethod]) -> None:
        self.calls = calls

    def _visible(self):
        return [c for c in self.calls if type(c).__name__ in self.VISIBLE]

    @property
    def texts(self) -> list[str]:
        return [
            getattr(c, "text", None) or getattr(c, "caption", None) or ""
            for c in self._visible()
        ]

    @property
    def last_text(self) -> str:
        return self.texts[-1] if self.texts else ""

    @property
    def alerts(self) -> list[str]:
        """Всплывающие ответы на нажатие кнопки."""
        return [
            c.text for c in self.calls
            if type(c).__name__ == "AnswerCallbackQuery" and c.text
        ]

    @property
    def answered_callback(self) -> bool:
        """Закрыт ли callback — иначе у человека висят «часики» (CLAUDE.md, 4.5)."""
        return any(type(c).__name__ == "AnswerCallbackQuery" for c in self.calls)

    def buttons(self) -> list[tuple[str, str | None]]:
        """(подпись, callback_data) всех инлайн-кнопок последнего сообщения."""
        for call in reversed(self._visible()):
            markup = getattr(call, "reply_markup", None)
            if isinstance(markup, InlineKeyboardMarkup):
                return [
                    (button.text, button.callback_data)
                    for row in markup.inline_keyboard for button in row
                ]
        return []

    def callbacks(self) -> list[str]:
        return [data for _, data in self.buttons() if data]

    def sent_to(self, chat_id: int) -> list[str]:
        """Что ушло конкретному человеку — например, уведомление мастеру."""
        return [
            getattr(c, "text", "") or ""
            for c in self.calls
            if type(c).__name__ == "SendMessage" and getattr(c, "chat_id", None) == chat_id
        ]


class Scenario:
    """
    Один человек разговаривает с ботом.

    Держит собственный telegram_id и отдаёт апдейты в настоящий диспетчер.
    """

    def __init__(self, dp, bot, session: RecordingSession, telegram_id: int,
                 first_name: str = "Тест") -> None:
        self.dp = dp
        self.bot = bot
        self.session = session
        self.user = User(id=telegram_id, is_bot=False, first_name=first_name)
        self.chat = Chat(id=telegram_id, type="private")
        self._last_bot_message_id = next(_ids)

    async def _feed(self, update: Update) -> Replies:
        start = len(self.session.calls)
        await self.dp.feed_update(self.bot, update)
        return Replies(self.session.calls[start:])

    async def say(self, text: str) -> Replies:
        """Человек пишет сообщение или жмёт кнопку reply-клавиатуры."""
        message = Message(
            message_id=next(_ids), date=datetime.now(),
            chat=self.chat, from_user=self.user, text=text,
        )
        return await self._feed(Update(update_id=next(_ids), message=message))

    async def command(self, text: str) -> Replies:
        """Команда: aiogram узнаёт её по сущности bot_command в начале текста."""
        from aiogram.types import MessageEntity

        command_length = len(text.split()[0])
        message = Message(
            message_id=next(_ids), date=datetime.now(),
            chat=self.chat, from_user=self.user, text=text,
            entities=[MessageEntity(type="bot_command", offset=0, length=command_length)],
        )
        return await self._feed(Update(update_id=next(_ids), message=message))

    async def press(self, callback_data: str) -> Replies:
        """Человек нажимает инлайн-кнопку под последним сообщением бота."""
        bot_message = Message(
            message_id=self._last_bot_message_id, date=datetime.now(),
            chat=self.chat, from_user=BOT_USER, text="…",
        )
        callback = CallbackQuery(
            id=str(next(_ids)), from_user=self.user, chat_instance="scenario",
            message=bot_message, data=callback_data,
        )
        return await self._feed(Update(update_id=next(_ids), callback_query=callback))

    async def share_contact(self, phone: str) -> Replies:
        """Кнопка «Поделиться контактом» из регистрации."""
        from aiogram.types import Contact

        message = Message(
            message_id=next(_ids), date=datetime.now(), chat=self.chat, from_user=self.user,
            contact=Contact(phone_number=phone, first_name=self.user.first_name,
                            user_id=self.user.id),
        )
        return await self._feed(Update(update_id=next(_ids), message=message))
