"""
Тесты метрик и алертов (docs/ROADMAP.md, Фаза 6).

`/health` отвечает «жив или нет», и этого мало: сервис бывает живым и при этом
сломанным. Заявка, которую мастер не разобрал третьи сутки, ничего не роняет —
клиент просто не дождался ответа и ушёл. Такое видно только по числам.

Самое тонкое место здесь — что считать застарелой заявкой. Считать надо
по времени подачи, а не по дате визита: запись на следующий месяц, поданная
час назад, застарелой не является, и метрика, которая считает иначе, будит
владельца зря. Разбудите его так трижды — и он перестанет читать алерты
вообще, вместе с настоящими.
"""
from datetime import timedelta

import database as db
import timeutils
from services import metrics


def _snapshot(**overrides) -> metrics.Metrics:
    base = {
        "users": 10, "stylists_active": 2, "bookings_today": 3,
        "bookings_pending": 1, "bookings_pending_stale": 0,
        "reviews_hidden": 0, "audit_entries_today": 5,
    }
    base.update(overrides)
    return metrics.Metrics(**base)


async def _booking(fixture_data, status=db.BOOKING_PENDING, created_days_ago=0,
                   when="2099-05-01 12:00"):
    session = fixture_data["session"]
    starts_at = timeutils.parse_slot(when)
    booking = db.Booking(
        user_id=fixture_data["client_user"].id,
        stylist_id=fixture_data["stylist"].id,
        service_id=fixture_data["service"].id,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=60),
        status=status,
        created_at=timeutils.now() - timedelta(days=created_days_ago),
    )
    session.add(booking)
    await session.commit()
    return booking


class TestPrometheusFormat:
    def test_every_metric_has_help_and_type(self):
        """Метрика без HELP и TYPE — это число без объяснения, что оно значит."""
        text = _snapshot().as_prometheus()

        names = [
            line.split()[0] for line in text.splitlines()
            if line and not line.startswith("#")
        ]
        for name in names:
            assert f"# HELP {name} " in text, f"{name} без HELP"
            assert f"# TYPE {name} " in text, f"{name} без TYPE"

    def test_names_are_prefixed(self):
        """Без префикса метрика «users» сольётся с чужой в общей системе."""
        text = _snapshot().as_prometheus()

        for line in text.splitlines():
            if line and not line.startswith("#"):
                assert line.startswith("maestro_"), line

    def test_values_are_numbers(self):
        text = _snapshot(users=7).as_prometheus()

        values = {
            line.split()[0]: line.split()[1]
            for line in text.splitlines() if line and not line.startswith("#")
        }
        assert values["maestro_users_total"] == "7"
        assert all(value.isdigit() for value in values.values())

    def test_output_ends_with_newline(self):
        """Prometheus не принимает ответ без завершающего перевода строки."""
        assert _snapshot().as_prometheus().endswith("\n")


class TestProblems:
    def test_quiet_when_everything_is_fine(self):
        """
        Ежедневное «всё хорошо» читать перестают через неделю, и вместе
        с ним перестают читать настоящие предупреждения.
        """
        assert metrics.problems(_snapshot()) == []

    def test_stale_pending_is_reported(self):
        found = metrics.problems(_snapshot(bookings_pending_stale=3))

        assert len(found) == 1
        assert "3" in found[0]

    def test_no_active_stylists_is_reported(self):
        found = metrics.problems(_snapshot(stylists_active=0, bookings_today=0))

        assert any("мастера" in item or "записаться" in item for item in found)

    def test_empty_day_is_not_reported_twice(self):
        """
        Когда мастеров нет вовсе, «нет записей на сегодня» — та же проблема,
        сказанная дважды. Два пункта об одном приучают их пролистывать.
        """
        found = metrics.problems(_snapshot(stylists_active=0, bookings_today=0))

        assert len(found) == 1

    def test_empty_day_is_reported_when_stylists_exist(self):
        found = metrics.problems(_snapshot(stylists_active=2, bookings_today=0))

        assert any("нет ни одной записи" in item for item in found)

    def test_problems_are_human_readable(self):
        """Алерт читает владелец сервиса, а не инженер."""
        found = metrics.problems(_snapshot(bookings_pending_stale=1))

        assert found[0][0].isupper()
        assert "_" not in found[0], "имя метрики вместо объяснения"


class TestCollect:
    async def test_counts_users_and_stylists(self, fixture_data):
        snapshot = await metrics.collect(fixture_data["session"])

        assert snapshot.users == 3, "в фикстуре мастер, клиент и посторонний"
        assert snapshot.stylists_active == 1

    async def test_pending_is_counted(self, fixture_data):
        snapshot = await metrics.collect(fixture_data["session"])

        assert snapshot.bookings_pending == 1, "заявка из фикстуры"

    async def test_stale_is_measured_from_submission_not_visit(self, fixture_data):
        """
        Главная тонкость. Запись на следующий месяц, поданная час назад,
        застарелой не является: метрика, считающая по дате визита, будила бы
        владельца зря — а разбуженный зря трижды перестаёт читать алерты.
        """
        session = fixture_data["session"]
        # Свежая заявка на далёкое будущее — застарелой быть не должна.
        await _booking(fixture_data, created_days_ago=0, when="2099-12-01 12:00")

        snapshot = await metrics.collect(session)

        assert snapshot.bookings_pending_stale == 0

    async def test_old_submission_is_stale(self, fixture_data):
        session = fixture_data["session"]
        await _booking(fixture_data, created_days_ago=3, when="2099-12-01 12:00")

        snapshot = await metrics.collect(session)

        assert snapshot.bookings_pending_stale == 1

    async def test_answered_booking_is_not_stale(self, fixture_data):
        """Мастер ответил — заявка больше не висит, сколько бы ни ждала."""
        session = fixture_data["session"]
        await _booking(
            fixture_data, status=db.BOOKING_APPROVED,
            created_days_ago=10, when="2099-12-01 12:00",
        )

        snapshot = await metrics.collect(session)

        assert snapshot.bookings_pending_stale == 0

    async def test_hidden_reviews_are_counted(self, fixture_data):
        session = fixture_data["session"]
        booking = fixture_data["booking"]
        booking.review_text = "Плохо"
        booking.review_hidden = True
        await session.commit()

        snapshot = await metrics.collect(session)

        assert snapshot.reviews_hidden == 1

    async def test_audit_entries_of_today_are_counted(self, fixture_data):
        from services import audit

        session = fixture_data["session"]
        audit.record_client(session, audit.BOOKING_CANCELLED, fixture_data["booking"])
        await session.commit()

        snapshot = await metrics.collect(session)

        assert snapshot.audit_entries_today == 1

    async def test_empty_database_does_not_crash(self, session):
        """Пустая база — рабочее состояние сразу после развёртывания."""
        snapshot = await metrics.collect(session)

        assert snapshot.users == 0
        assert metrics.problems(snapshot), "пустой сервис — повод сказать об этом"


class TestAlertsAreOptional:
    async def test_without_chat_id_nothing_is_sent(self, fixture_data, monkeypatch):
        """
        Без ALERT_CHAT_ID адресата нет. Задача обязана это переживать молча:
        она стоит в шедулере у всех, а чат настроен не у всех.
        """
        import scheduler

        monkeypatch.delenv("ALERT_CHAT_ID", raising=False)
        sent = []

        class FakeBot:
            async def send_message(self, **kwargs):
                sent.append(kwargs)

        await scheduler.send_health_alerts(FakeBot())

        assert sent == []

    async def test_alert_is_sent_when_there_is_a_problem(self, fixture_data, monkeypatch):
        import scheduler

        monkeypatch.setenv("ALERT_CHAT_ID", "-1001234567890")
        session = fixture_data["session"]
        await _booking(fixture_data, created_days_ago=5, when="2099-12-01 12:00")
        await session.commit()

        sent = []

        class FakeBot:
            async def send_message(self, **kwargs):
                sent.append(kwargs)

        await scheduler.send_health_alerts(FakeBot())

        assert len(sent) == 1
        assert "требует внимания" in sent[0]["text"]

    async def test_failed_send_does_not_crash_the_job(self, fixture_data, monkeypatch):
        """
        Шедулер не должен падать из-за недоступного чата: остальные задачи
        в том же процессе тоже перестали бы выполняться.
        """
        import scheduler

        monkeypatch.setenv("ALERT_CHAT_ID", "-1001234567890")
        await _booking(fixture_data, created_days_ago=5, when="2099-12-01 12:00")

        class BrokenBot:
            async def send_message(self, **kwargs):
                raise RuntimeError("чат не найден")

        await scheduler.send_health_alerts(BrokenBot())
