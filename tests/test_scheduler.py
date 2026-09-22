"""
Фоновые задачи (scheduler.py).

До этого файла задачи не проверялись вовсе — только копии их запросов
в test_offline_booking. Поэтому три ошибки прожили незамеченными:
часовое напоминание приходило с сырыми тегами <b>, визиты «не на ровный
час» не получали его совсем, а неудачная отправка всё равно числилась
отправленной.
"""
from datetime import timedelta
from types import SimpleNamespace

import pytest

import database as db
import scheduler
import timeutils

CYRILLIC = __import__("re").compile(r"[а-яА-ЯёЁ]")


class FakeBot:
    """Вместо Telegram: записывает отправленное, по желанию — отказывает."""

    def __init__(self, fail_for: set[int] | None = None):
        self.sent: list[dict] = []
        self.fail_for = fail_for or set()

    async def send_message(self, chat_id, text, **kwargs):
        if chat_id in self.fail_for:
            raise RuntimeError("Forbidden: bot was blocked by the user")
        self.sent.append({"chat_id": chat_id, "text": text, **kwargs})

    async def get_me(self):
        return SimpleNamespace(username="maestro_test_bot")


async def _approved_booking(fixture_data, starts_at):
    booking = fixture_data["booking"]
    booking.status = db.BOOKING_APPROVED
    booking.starts_at = starts_at
    booking.ends_at = starts_at + timedelta(hours=1)
    booking.reminder_day_sent = False
    booking.reminder_hour_sent = False
    await fixture_data["session"].commit()
    return booking


async def _flags(booking_id):
    async with db.async_session() as s:
        b = await s.get(db.Booking, booking_id)
        return b.reminder_day_sent, b.reminder_hour_sent


class TestWindows:
    """Окна напоминаний против частоты запуска."""

    def test_hour_window_not_narrower_than_interval(self):
        width = scheduler.HOUR_WINDOW[1] - scheduler.HOUR_WINDOW[0]
        assert width >= timedelta(minutes=scheduler.REMINDER_INTERVAL_MIN)

    @pytest.mark.parametrize("minute", [0, 10, 15, 20, 30, 45, 50])
    def test_every_start_minute_gets_an_hour_reminder(self, minute):
        """
        Прогоняем запуски по расписанию и смотрим, поймает ли хоть один
        визит, начинающийся в HH:minute. При ежечасном запуске и прежнем
        окне визит в 11:30 не ловился ни одним запуском.
        """
        visit = timeutils.parse_slot(f"2030-05-10 11:{minute:02d}")
        runs = [
            timeutils.parse_slot("2030-05-10 08:00") + timedelta(minutes=step)
            for step in range(0, 5 * 60, scheduler.REMINDER_INTERVAL_MIN)
        ]
        caught = [
            run for run in runs
            if scheduler.reminder_due(visit - run, day_sent=True, hour_sent=False)
            == scheduler.REMINDER_HOUR
        ]
        assert caught, f"визит в 11:{minute:02d} не получил часового напоминания"


class TestReminders:
    async def test_hour_reminder_is_html_and_escaped(self, fixture_data):
        now = timeutils.parse_slot("2030-05-10 10:15")
        booking = await _approved_booking(fixture_data, now + timedelta(hours=1))
        fixture_data["stylist"].name = "Али <VIP>"
        await fixture_data["session"].commit()

        bot = FakeBot()
        await scheduler.check_reminders(bot, now=now)

        assert len(bot.sent) == 1
        message = bot.sent[0]
        assert message["parse_mode"] == "HTML", "теги <b> ушли бы клиенту буквально"
        assert "&lt;VIP&gt;" in message["text"], "имя мастера попало в разметку без escape"
        assert await _flags(booking.id) == (False, True)

    async def test_day_reminder_in_client_language(self, fixture_data):
        now = timeutils.parse_slot("2030-05-10 10:00")
        await _approved_booking(fixture_data, now + timedelta(hours=24))
        fixture_data["client_user"].language_code = "uz"
        await fixture_data["session"].commit()

        bot = FakeBot()
        await scheduler.check_reminders(bot, now=now)

        assert len(bot.sent) == 1
        # Название услуги — данные, а не интерфейс.
        assert not CYRILLIC.search(bot.sent[0]["text"].replace("Стрижка", ""))

    async def test_sent_once(self, fixture_data):
        now = timeutils.parse_slot("2030-05-10 10:15")
        await _approved_booking(fixture_data, now + timedelta(hours=1))
        bot = FakeBot()

        await scheduler.check_reminders(bot, now=now)
        await scheduler.check_reminders(bot, now=now + timedelta(minutes=15))

        assert len(bot.sent) == 1, "напоминание ушло дважды"

    async def test_failed_delivery_is_not_marked_sent(self, fixture_data):
        """
        Раньше флаг ставился и при неудаче: временный сбой Telegram
        съедал напоминание насовсем.
        """
        now = timeutils.parse_slot("2030-05-10 10:15")
        booking = await _approved_booking(fixture_data, now + timedelta(hours=1))
        client_id = fixture_data["client_user"].telegram_id

        await scheduler.check_reminders(FakeBot(fail_for={client_id}), now=now)
        assert await _flags(booking.id) == (False, False)

        retry = FakeBot()
        await scheduler.check_reminders(retry, now=now + timedelta(minutes=15))
        assert len(retry.sent) == 1, "после сбоя напоминание не повторилось"

    async def test_one_failure_does_not_block_others(self, fixture_data):
        now = timeutils.parse_slot("2030-05-10 10:15")
        await _approved_booking(fixture_data, now + timedelta(hours=1))
        other = db.User(telegram_id=4004, first_name="Другой", phone_number="+998900000001")
        session = fixture_data["session"]
        session.add(other)
        await session.flush()
        second = db.Booking(
            user_id=other.id, stylist_id=fixture_data["stylist"].id,
            service_id=fixture_data["service"].id, status=db.BOOKING_APPROVED,
            starts_at=now + timedelta(minutes=70), ends_at=now + timedelta(minutes=130),
        )
        session.add(second)
        await session.commit()

        bot = FakeBot(fail_for={fixture_data["client_user"].telegram_id})
        await scheduler.check_reminders(bot, now=now)

        assert [m["chat_id"] for m in bot.sent] == [4004]


class TestFollowUps:
    async def _completed(self, fixture_data, now):
        booking = fixture_data["booking"]
        booking.status = db.BOOKING_COMPLETED
        booking.starts_at = now - timedelta(days=20)
        booking.ends_at = booking.starts_at + timedelta(hours=1)
        booking.follow_up_sent = False
        await fixture_data["session"].commit()
        return booking

    async def test_nameless_client_is_not_called_none(self, fixture_data):
        now = timeutils.parse_slot("2030-05-10 10:00")
        booking = await self._completed(fixture_data, now)
        fixture_data["client_user"].first_name = None
        await fixture_data["session"].commit()

        bot = FakeBot()
        await scheduler.check_follow_ups(bot, now=now)

        assert len(bot.sent) == 1
        assert "None" not in bot.sent[0]["text"]
        assert f"stylist_{fixture_data['stylist'].id}" in bot.sent[0]["text"]
        async with db.async_session() as s:
            assert (await s.get(db.Booking, booking.id)).follow_up_sent

    async def test_failed_follow_up_is_retried_later(self, fixture_data):
        now = timeutils.parse_slot("2030-05-10 10:00")
        booking = await self._completed(fixture_data, now)

        await scheduler.check_follow_ups(
            FakeBot(fail_for={fixture_data["client_user"].telegram_id}), now=now
        )
        async with db.async_session() as s:
            assert not (await s.get(db.Booking, booking.id)).follow_up_sent
