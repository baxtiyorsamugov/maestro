"""
Отправка ошибок в Sentry.

Ошибка на проде сейчас видна только в логах контейнера — то есть её никто
не видит, пока не пойдёт смотреть. Sentry превращает «однажды заметим»
в «узнаем сразу».

Подключение здесь — меньшая часть работы. Большая — вычистить из событий то,
чему в них не место. Sentry по умолчанию щедро прикладывает контекст: тело
запроса, локальные переменные из кадров стека, заголовки. В этом проекте
в таком контексте живут номера телефонов, `telegram_id`, пароль админки
и `BOT_TOKEN` — то есть ровно то, что `docs/SECURITY.md` запрещает выпускать
наружу. Поэтому `before_send` не фильтр «на всякий случай», а обязательная
часть подключения.

Без `SENTRY_DSN` модуль не делает ничего и ничего не ломает: локальная
разработка и тесты идут без Sentry вовсе.
"""
import logging
import re

import logutil

#: Ключи, значения которых вырезаем целиком, где бы они ни встретились:
#: в теле запроса, в локальных переменных кадра, в дополнительных данных.
SENSITIVE_KEYS = frozenset({
    "password", "admin_password", "bot_token", "token", "secret", "secret_key",
    "admin_secret_key", "phone", "phone_number", "db_pass", "pgpassword",
    "authorization", "cookie", "session", "api_key",
})

REDACTED = "[вырезано]"

#: Токен Telegram узнаётся по форме и может попасть в текст исключения
#: (например, в сообщении от aiohttp с URL запроса к api.telegram.org).
#:
#: Границы слова здесь использовать нельзя, и это не мелочь: в URL токен
#: идёт вплотную за «bot» — «api.telegram.org/bot123456789:AA...» — и `\b`
#: между «t» и «1» не срабатывает, потому что обе буквы словесные.
#: То есть самый частый реальный случай как раз и не вычищался бы.
TOKEN_PATTERN = re.compile(r"(?<!\d)\d{8,10}:[A-Za-z0-9_-]{30,}")

#: Телефон в узбекском формате. Ищем по форме, а не по имени поля: он попадает
#: в текст сообщений и в аргументы исключений, где имени поля уже нет.
PHONE_PATTERN = re.compile(r"\+?998\d{9}\b")


def _scrub_text(value: str) -> str:
    value = TOKEN_PATTERN.sub(REDACTED, value)
    return PHONE_PATTERN.sub(REDACTED, value)


def scrub(value, depth: int = 0):
    """
    Рекурсивно вычищает секреты из структуры события.

    Глубина ограничена: события Sentry бывают с циклами и очень глубокими
    вложенностями, а падение внутри before_send гасит отправку целиком —
    и мы остаёмся без ошибок вообще, не заметив этого.
    """
    if depth > 12:
        return value

    if isinstance(value, str):
        return _scrub_text(value)
    if isinstance(value, dict):
        return {
            key: (
                REDACTED
                if isinstance(key, str) and key.lower() in SENSITIVE_KEYS
                else scrub(item, depth + 1)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [scrub(item, depth + 1) for item in value]
    if isinstance(value, tuple):
        return tuple(scrub(item, depth + 1) for item in value)
    return value


def before_send(event, hint):
    """
    Последняя проверка перед отправкой события наружу.

    Исключения глушим намеренно: сбой в чистильщике не должен превращаться
    в отправку неочищенного события, но и в потерю всех ошибок — тоже.
    Поэтому при сбое событие отбрасывается, а причина остаётся в логе.
    """
    try:
        event = scrub(event)
        # Идентификатор пользователя — только маскированный (CLAUDE.md, 4.4).
        # Он всё ещё позволяет связать несколько ошибок одного человека,
        # но не говорит, кто это.
        user = event.get("user")
        if isinstance(user, dict) and user.get("id") is not None:
            user["id"] = logutil.mask_user(user["id"])
            user.pop("ip_address", None)
            user.pop("username", None)
        return event
    except Exception:
        logging.exception("sentry.scrub_failed событие не отправлено")
        return None


def init_sentry(dsn: str | None, environment: str, component: str) -> bool:
    """
    Подключает Sentry, если задан DSN. Возвращает True, если подключились.

    component («bot» или «admin») уходит тегом: обе половины шлют в один
    проект, и без тега непонятно, где именно сломалось.
    """
    if not dsn:
        return False

    try:
        import sentry_sdk
    except ImportError:
        logging.warning("sentry.not_installed SENTRY_DSN задан, но sentry-sdk не установлен")
        return False

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        # Явно, хотя это и значение по умолчанию: включённый send_default_pii
        # приложил бы к событиям IP, заголовки и тело запроса целиком.
        send_default_pii=False,
        # Локальные переменные кадров — самый щедрый источник утечки: в них
        # лежат объекты Message с телефоном и именем. Чистильщик их разбирает,
        # но не отправлять их вовсе надёжнее, чем вычищать.
        include_local_variables=False,
        before_send=before_send,
        # Трассировки не включаем: они стоят денег и здесь ничего не дают —
        # у бота нет ни одного запроса, который стоило бы профилировать.
        traces_sample_rate=0.0,
    )
    sentry_sdk.set_tag("component", component)
    logging.info("sentry.enabled component=%s environment=%s", component, environment)
    return True


def note_update(update_id, telegram_id) -> None:
    """
    Привязывает ошибку к конкретному апдейту.

    update_id связывает событие Sentry со строками в логе (их пишет
    LoggingMiddleware), а маскированный пользователь — с другими его ошибками.
    """
    try:
        import sentry_sdk
    except ImportError:
        return

    sentry_sdk.set_tag("update_id", update_id)
    sentry_sdk.set_user({"id": logutil.mask_user(telegram_id)})
