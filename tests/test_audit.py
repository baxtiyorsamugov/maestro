"""
Тесты журнала действий (docs/ROADMAP.md, Фаза 7).

На вопрос «кто отменил эту запись и когда» ответить было нечем: статус
менялся, а следов не оставалось. Для сервиса, где клиент и мастер спорят
о том, кто что отменил, это не мелочь, а отсутствие доказательства.

Два свойства, без которых журнал бесполезен, и оба легко потерять.

1. Запись журнала уезжает ТЕМ ЖЕ commit'ом, что и само изменение. Отдельная
   транзакция означала бы, что при сбое между ними изменение есть, а следа
   нет — то есть журнал врёт ровно в тех случаях, ради которых его читают.
2. Журнал переживает то, что описывает. Внешнего ключа на bookings нет
   намеренно: он утащил бы запись журнала следом за удалённой бронью.
"""
import inspect
from datetime import timedelta

import database as db
import timeutils
from services import audit


async def _booking(fixture_data, when="2098-07-01 12:00", status=db.BOOKING_PENDING):
    session = fixture_data["session"]
    starts_at = timeutils.parse_slot(when)
    booking = db.Booking(
        user_id=fixture_data["client_user"].id,
        stylist_id=fixture_data["stylist"].id,
        service_id=fixture_data["service"].id,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=60),
        status=status,
    )
    session.add(booking)
    await session.commit()
    return booking


class TestRecording:
    async def test_client_action_is_attributed_to_the_client(self, fixture_data):
        session = fixture_data["session"]
        booking = fixture_data["booking"]

        audit.record_client(session, audit.BOOKING_CANCELLED, booking)
        await session.commit()

        entry = (await audit.load_history_for_booking(session, booking.id))[0]
        assert entry.actor_kind == db.ACTOR_CLIENT
        assert entry.actor_user_id == fixture_data["client_user"].id
        assert entry.action == audit.BOOKING_CANCELLED

    async def test_stylist_action_is_attributed_to_the_stylist(self, fixture_data):
        session = fixture_data["session"]
        booking = fixture_data["booking"]

        audit.record_stylist(
            session, audit.BOOKING_APPROVED, booking,
            stylist_user_id=fixture_data["stylist_user"].id,
        )
        await session.commit()

        entry = (await audit.load_history_for_booking(session, booking.id))[0]
        assert entry.actor_kind == db.ACTOR_STYLIST
        assert entry.actor_user_id == fixture_data["stylist_user"].id

    async def test_admin_action_is_signed_by_login(self, fixture_data):
        """У администратора нет строки в users — подписываем логином."""
        session = fixture_data["session"]

        audit.record_admin(session, audit.REVIEW_HIDDEN, "owner", booking_id=1)
        await session.commit()

        entry = (await audit.load_feed(session))[0]
        assert entry.actor_kind == db.ACTOR_ADMIN
        assert entry.actor_user_id is None
        assert entry.actor_label == "owner"

    async def test_system_action_is_signed_by_scheduler(self, fixture_data):
        session = fixture_data["session"]

        audit.record_system(session, audit.BOOKING_COMPLETED, booking_id=1)
        await session.commit()

        entry = (await audit.load_feed(session))[0]
        assert entry.actor_kind == db.ACTOR_SYSTEM
        assert entry.actor_label == "scheduler"

    async def test_details_are_saved(self, fixture_data):
        session = fixture_data["session"]

        audit.record_client(
            session, audit.BOOKING_RESCHEDULED, fixture_data["booking"],
            details="2098-01-01 10:00 -> 2098-01-02 14:00",
        )
        await session.commit()

        entry = (await audit.load_feed(session))[0]
        assert "->" in entry.details

    async def test_long_details_are_trimmed(self, fixture_data):
        """Обрезаем на входе, а не ловим ошибку базы после самого действия."""
        session = fixture_data["session"]

        audit.record_client(
            session, audit.BOOKING_CANCELLED, fixture_data["booking"], details="я" * 5000
        )
        await session.commit()

        entry = (await audit.load_feed(session))[0]
        assert len(entry.details) == audit.DETAILS_MAX_LEN

    async def test_created_at_is_filled_automatically(self, fixture_data):
        session = fixture_data["session"]

        audit.record_client(session, audit.BOOKING_CANCELLED, fixture_data["booking"])
        await session.commit()

        entry = (await audit.load_feed(session))[0]
        assert entry.created_at is not None


class TestSameTransaction:
    """
    Главное свойство: журнал и изменение живут одной транзакцией.

    Иначе при сбое между ними отмена есть, а следа нет — и журнал врёт
    ровно там, где его и читают.
    """

    async def test_record_does_not_commit_on_its_own(self, fixture_data):
        session = fixture_data["session"]
        booking = fixture_data["booking"]
        # id берём до отката: после него объект просрочен, и обращение
        # к атрибуту полезло бы в базу вне greenlet-контекста.
        booking_id = booking.id

        audit.record_client(session, audit.BOOKING_CANCELLED, booking)
        await session.rollback()

        assert await audit.load_history_for_booking(session, booking_id) == []

    async def test_rollback_takes_both_the_change_and_the_record(self, fixture_data):
        session = fixture_data["session"]
        booking = fixture_data["booking"]

        booking_id = booking.id
        booking.status = db.BOOKING_CANCELLED
        audit.record_client(session, audit.BOOKING_CANCELLED, booking)
        await session.rollback()

        fresh = await session.get(db.Booking, booking_id)
        assert fresh.status == db.BOOKING_PENDING, "откат должен вернуть и статус"
        assert await audit.load_history_for_booking(session, booking_id) == []


class TestJournalOutlivesItsSubject:
    async def test_no_foreign_key_on_booking(self):
        """
        Прямая проверка схемы. Внешний ключ на bookings утащил бы запись
        журнала следом за удалённой бронью или запретил бы удаление —
        и в обоих случаях журнал перестал бы быть доказательством.
        """
        column = db.AuditLog.__table__.c.booking_id

        assert column.foreign_keys == set(), "на booking_id не должно быть FK"

    async def test_entry_survives_deleted_booking(self, fixture_data):
        from sqlalchemy import delete

        session = fixture_data["session"]
        booking = await _booking(fixture_data)
        booking_id = booking.id

        audit.record_client(session, audit.BOOKING_CANCELLED, booking)
        await session.commit()

        await session.execute(delete(db.Booking).where(db.Booking.id == booking_id))
        await session.commit()

        survived = await audit.load_history_for_booking(session, booking_id)
        assert len(survived) == 1, "журнал ушёл вместе с записью"


class TestHistoryAndFeed:
    async def test_history_is_oldest_first(self, fixture_data):
        """История одной записи читается сверху вниз, как рассказ."""
        session = fixture_data["session"]
        booking = fixture_data["booking"]

        audit.record_client(session, audit.BOOKING_CREATED, booking)
        audit.record_stylist(session, audit.BOOKING_APPROVED, booking)
        audit.record_client(session, audit.BOOKING_CANCELLED, booking)
        await session.commit()

        actions = [e.action for e in await audit.load_history_for_booking(session, booking.id)]

        assert actions == [
            audit.BOOKING_CREATED, audit.BOOKING_APPROVED, audit.BOOKING_CANCELLED
        ]

    async def test_feed_is_newest_first(self, fixture_data):
        """Лента админки — наоборот: разбирают то, что только что случилось."""
        session = fixture_data["session"]
        booking = fixture_data["booking"]

        audit.record_client(session, audit.BOOKING_CREATED, booking)
        audit.record_client(session, audit.BOOKING_CANCELLED, booking)
        await session.commit()

        actions = [e.action for e in await audit.load_feed(session)]

        assert actions[0] == audit.BOOKING_CANCELLED

    async def test_history_ignores_other_bookings(self, fixture_data):
        session = fixture_data["session"]
        mine = fixture_data["booking"]
        other = await _booking(fixture_data, when="2098-08-01 12:00")

        audit.record_client(session, audit.BOOKING_CANCELLED, mine)
        audit.record_client(session, audit.BOOKING_CANCELLED, other)
        await session.commit()

        assert len(await audit.load_history_for_booking(session, mine.id)) == 1

    async def test_feed_is_capped(self, fixture_data):
        session = fixture_data["session"]
        for _ in range(audit.FEED_LIMIT + 5):
            audit.record_client(session, audit.BOOKING_CANCELLED, fixture_data["booking"])
        await session.commit()

        assert len(await audit.load_feed(session)) == audit.FEED_LIMIT

    async def test_actor_is_loaded_for_the_feed(self, fixture_data):
        """
        Лента показывает имя автора. Без joinedload обращение к нему
        в async-контексте бросит MissingGreenlet (CLAUDE.md, 4.3).
        """
        session = fixture_data["session"]
        audit.record_client(session, audit.BOOKING_CANCELLED, fixture_data["booking"])
        await session.commit()

        entries = await audit.load_feed(session)
        session.expunge_all()

        assert entries[0].actor.first_name == "Клиент"


class TestAdminPage:
    def test_every_action_has_a_human_label(self):
        """
        Журнал читает человек: «booking.approved» в таблице заставляет
        держать словарь в голове.
        """
        from admin_panel import AUDIT_LABELS

        known = {
            value for name, value in vars(audit).items()
            if name.isupper() and isinstance(value, str) and "." in value
        }
        missing = known - set(AUDIT_LABELS)
        assert missing == set(), f"без подписи в админке: {missing}"

    def test_empty_journal_says_so(self):
        from admin_panel import _render_audit

        assert "Журнал пуст" in _render_audit([])

    def test_details_are_escaped(self):
        """
        В details попадает имя офлайн-клиента, которое ввёл мастер.
        Эта строка уходит в HTML-страницу админки.
        """
        from admin_panel import _render_audit

        html = _render_audit([{
            "when": "2098-01-01 12:00",
            "action": "Запись офлайн-клиента",
            "actor": "Мастер (мастер)",
            "booking_id": 1,
            "details": "<script>alert(1)</script>",
        }])

        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html

    def test_actor_label_is_escaped(self):
        from admin_panel import _render_audit

        html = _render_audit([{
            "when": "2098-01-01 12:00", "action": "Отменена клиентом",
            "actor": "<b>Хакер</b>", "booking_id": 1, "details": "",
        }])

        assert "<b>Хакер</b>" not in html

    def test_page_is_read_only(self):
        """
        Журнал, который можно поправить, не доказывает ничего. На странице
        не должно быть ни форм, ни кнопок действий.
        """
        from admin_panel import _render_audit

        html = _render_audit([{
            "when": "2098-01-01 12:00", "action": "Отменена клиентом",
            "actor": "Клиент", "booking_id": 1, "details": "",
        }])

        assert "<form" not in html
        assert "<button" not in html


class TestHandlersWriteToTheJournal:
    """
    Прямая проверка исходников: если кто-то добавит смену статуса без
    записи в журнал, история снова станет дырявой, и заметить это
    поведенческим тестом трудно — всё продолжит работать.
    """

    def test_stylist_actions_are_logged(self):
        from handlers.stylist import bookings

        for handler, action in (
            (bookings.approve_booking, "BOOKING_APPROVED"),
            (bookings.decline_booking, "BOOKING_DECLINED"),
            (bookings.complete_booking, "BOOKING_COMPLETED"),
        ):
            source = inspect.getsource(handler)
            assert "audit.record_stylist" in source, f"{handler.__name__} не пишет в журнал"
            assert action in source

    def test_client_cancel_is_logged(self):
        from handlers.client import profile

        source = inspect.getsource(profile.cancel_booking)

        assert "audit.record_client" in source
        assert "BOOKING_CANCELLED" in source

    def test_reschedule_is_logged(self):
        from handlers.client import booking

        source = inspect.getsource(booking.finalize_booking)

        assert "audit.record_client" in source
        assert "BOOKING_RESCHEDULED" in source

    def test_offline_booking_is_logged(self):
        from handlers.stylist import offline_booking

        source = inspect.getsource(offline_booking._save)

        assert "audit.record_stylist" in source
        assert "BOOKING_CREATED_OFFLINE" in source

    def test_review_moderation_is_logged(self):
        import admin_panel

        source = inspect.getsource(admin_panel.toggle_review_visibility)

        assert "audit.record_admin" in source
