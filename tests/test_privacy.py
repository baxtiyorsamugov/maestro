"""
Тесты удаления аккаунта (docs/ROADMAP.md, Фаза 7).

Удалить аккаунт по просьбе человека было нельзя вовсе.

Главное решение — обезличивать, а не стирать всё подряд. Удаляется то, что
указывает на человека; остаются обезличенные факты, от которых зависят другие.
Ошибиться можно в обе стороны, и обе ошибки тихие:

  * недоудалить — человек уверен, что его данных нет, а имя лежит в журнале;
  * переудалить — у мастера задним числом исчезает выручка за прошлые месяцы
    и падает рейтинг, который он заработал работой.

Поэтому проверяется и то, что ушло, и то, что осталось, — каждое отдельно.
"""
from datetime import timedelta

import pytest
from sqlalchemy import func, select

import database as db
import timeutils
from services import audit, privacy


async def _visit(fixture_data, when, status=db.BOOKING_COMPLETED, **extra):
    session = fixture_data["session"]
    starts_at = timeutils.parse_slot(when) if isinstance(when, str) else when
    booking = db.Booking(
        user_id=fixture_data["client_user"].id,
        stylist_id=fixture_data["stylist"].id,
        service_id=fixture_data["service"].id,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=60),
        status=status,
        **extra,
    )
    session.add(booking)
    await session.commit()
    return booking


async def _count(session, model, *where):
    return await session.scalar(select(func.count()).select_from(model).where(*where)) or 0


class TestPersonIsGone:
    """То, что указывает на человека, должно исчезнуть целиком."""

    async def test_user_row_is_deleted(self, fixture_data):
        session = fixture_data["session"]
        client_id = fixture_data["client_user"].id

        await privacy.delete_client_account(session, client_id)

        assert await session.get(db.User, client_id) is None

    async def test_phone_and_name_are_nowhere(self, fixture_data):
        """
        Не только строка users: телефон и имя не должны остаться ни в одной
        таблице. Проверяем поиском по всей базе, а не по той колонке, где
        им положено лежать.
        """
        session = fixture_data["session"]
        client = fixture_data["client_user"]
        # Имя нарочно редкое: «Клиент» из фикстуры слишком общее и нашлось бы
        # в посторонних строках, превратив проверку в шум.
        client.first_name = "Зульфизар"
        await session.commit()
        # Отзыв с именем внутри — ещё одно место, где оно могло бы застрять.
        await _visit(fixture_data, "2098-04-01 12:00", rating=5,
                     review_text="Спасибо, Зульфизар довольна")

        await privacy.delete_client_account(session, client.id)

        async with db.engine.connect() as conn:
            from sqlalchemy import text

            for table in db.Base.metadata.sorted_tables:
                for column in table.columns:
                    if not str(column.type).upper().startswith(("VARCHAR", "TEXT", "STRING")):
                        continue
                    for needle, what in (("998901234567", "телефон"), ("Зульфизар", "имя")):
                        # Образец идёт параметром. Имена таблицы и колонки
                        # параметром не передать — они из метаданных SQLAlchemy,
                        # а не от пользователя, отсюда и noqa.
                        found = await conn.scalar(
                            text(
                                f"SELECT count(*) FROM {table.name} "  # noqa: S608
                                f"WHERE {column.name} LIKE :pattern"
                            ),
                            {"pattern": f"%{needle}%"},
                        )
                        assert not found, f"{what} остался в {table.name}.{column.name}"

    async def test_review_text_is_removed(self, fixture_data):
        """Отзыв — слова человека, в них бывает имя."""
        session = fixture_data["session"]
        visit = await _visit(
            fixture_data, "2098-01-01 12:00", rating=5, review_text="Меня зовут Гульнора"
        )

        await privacy.delete_client_account(session, fixture_data["client_user"].id)

        fresh = await session.get(db.Booking, visit.id)
        assert fresh.review_text is None

    async def test_favorites_are_removed(self, fixture_data):
        session = fixture_data["session"]
        session.add(db.Favorite(
            user_id=fixture_data["client_user"].id, stylist_id=fixture_data["stylist"].id
        ))
        await session.commit()

        await privacy.delete_client_account(session, fixture_data["client_user"].id)

        assert await _count(session, db.Favorite) == 0

    async def test_audit_no_longer_points_at_the_person(self, fixture_data):
        """
        Журнал — доказательство, его не чистят. Но «кто это был» из него
        должно исчезнуть, иначе просьба не выполнена.
        """
        session = fixture_data["session"]
        client_id = fixture_data["client_user"].id
        audit.record_client(session, audit.BOOKING_CANCELLED, fixture_data["booking"])
        await session.commit()

        await privacy.delete_client_account(session, client_id)

        assert await _count(session, db.AuditLog, db.AuditLog.actor_user_id == client_id) == 0


class TestOthersKeepTheirFacts:
    """То, от чего зависят другие, должно остаться — без привязки к человеку."""

    async def test_past_visit_survives_for_the_stylist(self, fixture_data):
        """
        Стереть визит значило бы переписать задним числом выручку мастера
        за прошлые месяцы.
        """
        session = fixture_data["session"]
        visit = await _visit(fixture_data, "2098-02-01 12:00")

        await privacy.delete_client_account(session, fixture_data["client_user"].id)

        fresh = await session.get(db.Booking, visit.id)
        assert fresh is not None, "визит пропал — выручка мастера изменилась задним числом"
        assert fresh.user_id is None, "визит всё ещё указывает на человека"
        assert fresh.status == db.BOOKING_COMPLETED

    async def test_rating_survives(self, fixture_data):
        """На звёздах держится рейтинг, который мастер заработал работой."""
        session = fixture_data["session"]
        visit = await _visit(fixture_data, "2098-03-01 12:00", rating=4, review_text="Хорошо")

        await privacy.delete_client_account(session, fixture_data["client_user"].id)

        assert (await session.get(db.Booking, visit.id)).rating == 4

    async def test_audit_entry_survives_anonymised(self, fixture_data):
        session = fixture_data["session"]
        audit.record_client(session, audit.BOOKING_CANCELLED, fixture_data["booking"])
        await session.commit()

        await privacy.delete_client_account(session, fixture_data["client_user"].id)

        entries = await audit.load_history_for_booking(session, fixture_data["booking"].id)
        cancelled = [e for e in entries if e.action == audit.BOOKING_CANCELLED]
        assert cancelled, "запись журнала пропала — доказательство уничтожено"
        assert cancelled[0].actor_label == privacy.DELETED_ACTOR_LABEL

    async def test_deletion_itself_is_recorded(self, fixture_data):
        """
        Без этого на вопрос «удалили ли вы мои данные и когда» не было бы
        ответа: удаление не оставляло бы следа.
        """
        session = fixture_data["session"]

        await privacy.delete_client_account(session, fixture_data["client_user"].id)

        assert await _count(
            session, db.AuditLog, db.AuditLog.action == privacy.ACCOUNT_DELETED
        ) == 1

    async def test_stylist_and_other_users_are_untouched(self, fixture_data):
        session = fixture_data["session"]

        await privacy.delete_client_account(session, fixture_data["client_user"].id)

        assert await session.get(db.User, fixture_data["stylist_user"].id) is not None
        assert await session.get(db.User, fixture_data["intruder"].id) is not None
        assert await session.get(db.Stylist, fixture_data["stylist"].id) is not None


class TestUpcomingVisits:
    async def test_future_booking_is_cancelled(self, fixture_data):
        """
        Мастер ждёт человека, которого больше нет, и должен узнать об этом
        до визита, а не в момент.
        """
        session = fixture_data["session"]
        future = await _visit(
            fixture_data, timeutils.now() + timedelta(days=3), status=db.BOOKING_APPROVED
        )

        report = await privacy.delete_client_account(session, fixture_data["client_user"].id)

        assert (await session.get(db.Booking, future.id)).status == db.BOOKING_CANCELLED
        # Заявка из фикстуры стоит на 2099 год в статусе pending — она тоже
        # будущая и активная, и отменить её так же правильно.
        assert {v.booking_id for v in report.cancelled} == {
            future.id, fixture_data["booking"].id
        }

    async def test_stylist_contact_is_returned_for_the_notice(self, fixture_data):
        session = fixture_data["session"]
        await _visit(fixture_data, timeutils.now() + timedelta(days=3), status=db.BOOKING_PENDING)

        report = await privacy.delete_client_account(session, fixture_data["client_user"].id)

        assert report.cancelled[0].stylist_telegram_id == fixture_data["stylist_user"].telegram_id

    async def test_past_bookings_are_not_cancelled(self, fixture_data):
        """Завершённый визит отменять бессмысленно — он уже был."""
        session = fixture_data["session"]
        past = await _visit(fixture_data, "2098-01-01 12:00", status=db.BOOKING_COMPLETED)

        report = await privacy.delete_client_account(session, fixture_data["client_user"].id)

        assert (await session.get(db.Booking, past.id)).status == db.BOOKING_COMPLETED
        assert past.id not in [v.booking_id for v in report.cancelled]

    async def test_cancellation_is_in_the_journal(self, fixture_data):
        session = fixture_data["session"]
        future = await _visit(
            fixture_data, timeutils.now() + timedelta(days=3), status=db.BOOKING_APPROVED
        )

        await privacy.delete_client_account(session, fixture_data["client_user"].id)

        history = await audit.load_history_for_booking(session, future.id)
        assert any(e.action == audit.BOOKING_CANCELLED for e in history)

    async def test_freed_slot_is_available_again(self, fixture_data):
        """
        Отменённая запись выходит из частичного уникального индекса:
        время снова можно отдать другому клиенту.
        """
        from services.booking import get_available_slots_for_date

        session = fixture_data["session"]
        day = timeutils.today() + timedelta(days=5)
        session.add(db.Schedule(
            stylist_id=fixture_data["stylist"].id, day_of_week=day.isoweekday(),
            start_time="10:00", end_time="14:00",
        ))
        await session.commit()
        await _visit(
            fixture_data, timeutils.parse_slot(f"{day:%Y-%m-%d} 12:00"),
            status=db.BOOKING_APPROVED,
        )

        await privacy.delete_client_account(session, fixture_data["client_user"].id)

        _, slots = await get_available_slots_for_date(
            session, fixture_data["stylist"].id, fixture_data["service"].id, day
        )
        assert "12:00" in slots


class TestRefusalsAndEdgeCases:
    async def test_stylist_cannot_delete_themselves(self, fixture_data):
        """
        За учёткой мастера стоят подписка, расписание и клиенты с записями
        на будущее — это решение не для одной кнопки.
        """
        session = fixture_data["session"]

        with pytest.raises(privacy.DeletionRefused) as refused:
            await privacy.delete_client_account(session, fixture_data["stylist_user"].id)

        assert refused.value.reason_key == "privacy_stylist_refused"
        assert await session.get(db.User, fixture_data["stylist_user"].id) is not None

    async def test_second_deletion_is_harmless(self, fixture_data):
        """Повторное нажатие на устаревшей кнопке не должно ничего ломать."""
        session = fixture_data["session"]
        client_id = fixture_data["client_user"].id

        await privacy.delete_client_account(session, client_id)
        again = await privacy.delete_client_account(session, client_id)

        assert again.bookings_unlinked == 0

    async def test_user_with_nothing_can_be_deleted(self, fixture_data):
        """Человек, который только зарегистрировался и ничего не делал."""
        session = fixture_data["session"]

        await privacy.delete_client_account(session, fixture_data["intruder"].id)

        assert await session.get(db.User, fixture_data["intruder"].id) is None

    async def test_person_can_register_again(self, fixture_data):
        """После удаления /start должен давать чистую новую учётную запись."""
        session = fixture_data["session"]
        telegram_id = fixture_data["client_user"].telegram_id

        await privacy.delete_client_account(session, fixture_data["client_user"].id)
        session.add(db.User(telegram_id=telegram_id, first_name="Снова"))
        await session.commit()

        assert await _count(session, db.User, db.User.telegram_id == telegram_id) == 1


class TestSummary:
    async def test_counts_what_is_stored(self, fixture_data):
        session = fixture_data["session"]
        await _visit(fixture_data, "2098-01-01 12:00", rating=5, review_text="Хорошо")
        session.add(db.Favorite(
            user_id=fixture_data["client_user"].id, stylist_id=fixture_data["stylist"].id
        ))
        await session.commit()

        summary = await privacy.summarize(session, fixture_data["client_user"])

        assert summary.has_phone is True
        assert summary.bookings == 2, "заявка из фикстуры и визит"
        assert summary.reviews == 1
        assert summary.favorites == 1

    async def test_upcoming_is_counted_separately(self, fixture_data):
        """
        Будущие визиты — единственное последствие, которое касается
        не только самого человека, но и мастера. Показываем их отдельно.
        """
        session = fixture_data["session"]
        before = (await privacy.summarize(session, fixture_data["client_user"])).upcoming
        await _visit(fixture_data, timeutils.now() + timedelta(days=2), status=db.BOOKING_APPROVED)

        summary = await privacy.summarize(session, fixture_data["client_user"])

        # Считаем прирост, а не абсолют: заявка из фикстуры тоже будущая.
        assert summary.upcoming == before + 1


class TestPolicyText:
    def test_policy_exists_in_both_languages(self):
        import texts

        for lang in ("ru", "uz"):
            assert len(texts.get_text("privacy_policy", lang)) > 300

    def test_policy_does_not_promise_what_code_does_not_do(self):
        """
        Политика — почти юридический текст. Обещание, которое код не выполняет,
        хуже его отсутствия: сроков автоудаления в коде нет, значит, и в тексте
        их быть не должно.
        """
        import texts

        text = texts.get_text("privacy_policy", "ru").lower()
        for promise in ("через 30 дней", "через год", "автоматически удаля"):
            assert promise not in text, f"политика обещает то, чего нет в коде: {promise}"

    def test_policy_names_what_survives(self):
        """Честно сказать, что остаётся, — часть выполнения просьбы."""
        import texts

        text = texts.get_text("privacy_policy", "ru")
        assert "прошлых визитов" in text
        assert "оценки" in text


class TestMenuButtonDoesNotBecomeASearchQuery:
    def test_new_button_is_recognised_as_menu(self):
        """
        Список кнопок меню раньше перечислялся руками, и «Мои данные»,
        нажатая посреди поиска, ушла бы поисковым запросом по имени мастера.
        """
        import texts
        from handlers.client.search import is_client_main_menu_button

        for variant in texts.all_variants("my_data"):
            assert is_client_main_menu_button(variant), variant

    def test_every_menu_button_is_recognised(self):
        """Следующая кнопка не должна повторить ту же ошибку."""
        import texts
        from handlers.client.search import is_client_main_menu_button

        for key in texts.BUTTONS:
            for variant in texts.all_variants(key):
                assert is_client_main_menu_button(variant), f"{key}: {variant}"

    def test_ordinary_text_is_not_a_button(self):
        from handlers.client.search import is_client_main_menu_button

        assert is_client_main_menu_button("Алишер") is False


class TestForeignKeysAreEnforced:
    async def test_sqlite_checks_foreign_keys(self, fixture_data):
        """
        SQLite по умолчанию внешние ключи не проверяет. Без этого ошибка
        в порядке удаления проходит на локальной базе и в основном прогоне CI
        почти незамеченной, а на проде удаление аккаунта падает.

        Проверяем поведением: удалить пользователя, на которого ссылаются
        визиты, должно быть нельзя.
        """
        from sqlalchemy import delete
        from sqlalchemy.exc import IntegrityError

        session = fixture_data["session"]
        client_id = fixture_data["client_user"].id

        try:
            await session.execute(delete(db.User).where(db.User.id == client_id))
            await session.commit()
        except IntegrityError:
            await session.rollback()
        else:
            raise AssertionError(
                "пользователь удалился, хотя на него ссылается визит: "
                "внешние ключи не проверяются"
            )
