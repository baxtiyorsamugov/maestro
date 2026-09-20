"""
Тесты отправки ошибок в Sentry (docs/ROADMAP.md, Фаза 6).

Подключить Sentry — три строки. Опасная часть в другом: Sentry по умолчанию
щедро прикладывает контекст, а в контексте этого проекта живут номера
телефонов, telegram_id, пароль админки и BOT_TOKEN. Отправить их наружу —
значит нарушить ровно то, что запрещает docs/SECURITY.md, и заметить это
некому: события уходят молча и выглядят нормально.

Поэтому before_send здесь не «фильтр на всякий случай», а обязательная часть
подключения, и проверяется она отдельно от всего остального.

Чек-лист в docs/SECURITY.md прямо требует: «Sentry подключён, в события
не попадают персональные данные». Эти тесты — доказательство второй половины.
"""
import logutil
import observability


def _event(**extra):
    """Скелет события Sentry: до отправки оно обычный словарь."""
    base = {"level": "error", "platform": "python"}
    base.update(extra)
    return base


class TestSecretsAreScrubbed:
    def test_password_field_is_removed(self):
        event = observability.before_send(
            _event(request={"data": {"username": "owner", "password": "hunter2"}}), None
        )

        assert "hunter2" not in str(event)
        assert event["request"]["data"]["username"] == "owner", "лишнего не вычистили"

    def test_admin_secret_key_is_removed(self):
        event = observability.before_send(
            _event(extra={"admin_secret_key": "super-long-secret-value"}), None
        )

        assert "super-long-secret-value" not in str(event)

    def test_db_password_is_removed(self):
        event = observability.before_send(_event(extra={"DB_PASS": "prod-db-pass"}), None)

        assert "prod-db-pass" not in str(event)

    def test_field_name_case_does_not_matter(self):
        event = observability.before_send(_event(extra={"PASSWORD": "hunter2"}), None)

        assert "hunter2" not in str(event)

    def test_scrubbing_reaches_nested_structures(self):
        """
        Секрет редко лежит на верхнем уровне. Он приходит внутри кадра стека,
        внутри списка аргументов, внутри тела запроса.
        """
        event = observability.before_send(
            _event(exception={"values": [{"stacktrace": {"frames": [
                {"vars": {"settings": {"password": "hunter2"}}}
            ]}}]}),
            None,
        )

        assert "hunter2" not in str(event)


class TestTokenIsScrubbedByShape:
    """
    BOT_TOKEN попадает в события не как поле, а внутри текста: aiohttp
    кладёт в сообщение об ошибке URL запроса к api.telegram.org вместе
    с токеном. Имени поля там нет — узнаём по форме.
    """

    def test_token_in_message_is_removed(self):
        token = "123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"
        event = observability.before_send(
            _event(message=f"POST https://api.telegram.org/bot{token}/sendMessage failed"),
            None,
        )

        assert token not in str(event)
        assert observability.REDACTED in event["message"]

    def test_token_inside_exception_value_is_removed(self):
        token = "987654321:AAFakeTokenValueLongEnoughToMatch01"
        event = observability.before_send(
            _event(exception={"values": [{"value": f"Unauthorized for {token}"}]}), None
        )

        assert token not in str(event)

    def test_ordinary_numbers_are_not_touched(self):
        """Идентификатор записи не должен пострадать от чистки токенов."""
        event = observability.before_send(_event(message="booking_id=123456 не найдена"), None)

        assert "123456" in event["message"]


class TestPhoneIsScrubbedByShape:
    def test_phone_in_message_is_removed(self):
        event = observability.before_send(
            _event(message="не дозвонились до +998901234567"), None
        )

        assert "998901234567" not in str(event)

    def test_phone_without_plus_is_removed_too(self):
        event = observability.before_send(_event(extra={"note": "998901234567"}), None)

        assert "998901234567" not in str(event)

    def test_phone_field_is_removed_by_name_as_well(self):
        """Телефон другой страны не подойдёт под шаблон — ловим по имени поля."""
        event = observability.before_send(
            _event(extra={"phone_number": "+7 900 000-00-00"}), None
        )

        assert "900 000" not in str(event)


class TestUserIsMasked:
    def test_telegram_id_becomes_a_token(self):
        """
        Маскированный идентификатор всё ещё связывает ошибки одного человека,
        но не говорит, кто это (CLAUDE.md, 4.4).
        """
        event = observability.before_send(_event(user={"id": 123456789}), None)

        assert event["user"]["id"] == logutil.mask_user(123456789)
        assert "123456789" not in str(event["user"])

    def test_ip_and_username_are_dropped(self):
        event = observability.before_send(
            _event(user={"id": 1, "ip_address": "203.0.113.7", "username": "gulnora"}),
            None,
        )

        assert "ip_address" not in event["user"]
        assert "username" not in event["user"]

    def test_event_without_user_survives(self):
        event = observability.before_send(_event(message="что-то сломалось"), None)

        assert event is not None


class TestRobustness:
    def test_broken_event_is_dropped_not_sent(self, caplog):
        """
        Сбой в чистильщике не должен приводить к отправке неочищенного
        события. Отбрасываем и пишем в лог, чтобы это не осталось незамеченным.
        """
        class Explodes(dict):
            # Ломаем именно items(): scrub ходит по словарю через него,
            # а не через get — на get чистильщик бы даже не споткнулся.
            def items(self):
                raise RuntimeError("бум")

        assert observability.before_send(Explodes(a=1), None) is None

    def test_deep_structure_does_not_recurse_forever(self):
        """
        События Sentry бывают очень глубокими. Падение внутри before_send
        гасит отправку целиком — и мы остаёмся без ошибок вообще.
        """
        deep = current = {}
        for _ in range(200):
            current["next"] = {}
            current = current["next"]
        current["password"] = "hunter2"

        assert observability.before_send(_event(extra=deep), None) is not None

    def test_non_string_values_survive(self):
        event = observability.before_send(
            _event(extra={"count": 42, "flag": True, "nothing": None}), None
        )

        assert event["extra"]["count"] == 42
        assert event["extra"]["flag"] is True
        assert event["extra"]["nothing"] is None


class TestInitIsOptional:
    def test_without_dsn_nothing_happens(self):
        """
        Локальная разработка и тесты идут без Sentry вовсе. Модуль обязан
        это переживать молча, а не падать на старте.
        """
        assert observability.init_sentry(None, "development", "bot") is False

    def test_empty_dsn_counts_as_absent(self):
        assert observability.init_sentry("", "development", "bot") is False

    def test_note_update_without_sentry_is_safe(self):
        """Вызов из обработчика ошибок не должен падать, когда Sentry выключен."""
        observability.note_update(42, 123456789)


class TestSettings:
    def test_sentry_is_not_required(self):
        """Требовать DSN нельзя: без него проект должен запускаться."""
        import config

        problems = config.describe_problems(groups=("bot", "database"))
        assert all("SENTRY" not in problem for problem in problems)

    def test_environment_has_a_default(self):
        import config

        assert config.load_sentry_settings().environment
