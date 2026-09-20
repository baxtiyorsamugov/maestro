"""
Помощники для логов.

CLAUDE.md, 4.4 запрещает писать `telegram_id` в логи открытым текстом, но
правило было только на бумаге: девять мест печатали `user_id=<настоящий id>`.
Логи проекта однажды уже лежали в репозитории (docs/SECURITY.md, S-3), так что
это не теоретический риск.

`mask_user()` даёт короткий стабильный токен: строки одного пользователя
по-прежнему сходятся между собой, а сам идентификатор из лога не достать.

Соль берётся из секрета, который у процесса и так есть. Без соли маскировка
была бы просто затемнением: пространство идентификаторов Telegram конечно,
и хеши по нему перебираются. С солью — уже нет.
"""
import hashlib
import json
import logging
import logging.handlers
import os
from functools import lru_cache
from pathlib import Path

#: Длина токена в шестнадцатеричных символах. Восьми хватает, чтобы строки
#: одного пользователя не путались с чужими в пределах одного лога.
MASK_LEN = 8

#: Порядок источников соли: специально заведённая переменная, затем любой
#: секрет, который у процесса уже есть. Бот запускается без ADMIN_SECRET_KEY,
#: админка — без BOT_TOKEN, поэтому перебираем оба.
SALT_SOURCES = ("LOG_SALT", "ADMIN_SECRET_KEY", "BOT_TOKEN")


@lru_cache(maxsize=1)
def _salt() -> bytes:
    for name in SALT_SOURCES:
        value = os.getenv(name)
        if value and value.strip():
            return hashlib.blake2s(value.strip().encode(), digest_size=16).digest()
    # Осознанный запасной вариант: без секрета в окружении маскировка
    # остаётся затемнением, а не защитой. Падать из-за этого нельзя —
    # логи должны работать всегда.
    return b"maestro-log-unsalted"


@lru_cache(maxsize=4096)
def mask_user(telegram_id: int | str | None) -> str:
    """
    Короткий стабильный токен вместо telegram_id.

    Кеш нужен не ради скорости хеша, а чтобы горячие строки логов
    (антифлуд, отказы доступа) не считали одно и то же по многу раз.
    """
    if telegram_id is None:
        return "anon"
    digest = hashlib.blake2s(
        str(telegram_id).encode(), key=_salt(), digest_size=MASK_LEN // 2
    )
    return digest.hexdigest()


def reset_salt_cache() -> None:
    """Сброс кешей — нужен тестам, которые подменяют окружение."""
    _salt.cache_clear()
    mask_user.cache_clear()


# --- Настройка вывода ------------------------------------------------------
#
# Логи писались строкой «время уровень имя: сообщение». Человеку читать удобно,
# машине — нет: чтобы найти все строки одного апдейта, приходится придумывать
# регулярки под собственный же формат. JSON снимает этот вопрос и стоит одной
# переменной окружения.
#
# По умолчанию остаётся текст: при локальной разработке JSON в терминале
# читать невозможно. В контейнере ставится LOG_FORMAT=json.

#: Поля LogRecord, которые не несут ничего полезного в JSON и только раздувают
#: строку. Всё, чего здесь нет, считается «дополнительным» и уезжает в запись:
#: так logging.info("...", extra={"update_id": 5}) работает сам собой.
_NOISE_FIELDS = frozenset({
    "args", "created", "exc_info", "exc_text", "filename", "funcName",
    "levelno", "lineno", "module", "msecs", "msg", "name", "pathname",
    "process", "processName", "relativeCreated", "stack_info", "thread",
    "threadName", "taskName", "levelname", "message", "asctime",
    # Uvicorn кладёт сюда ту же строку с ANSI-кодами для раскраски терминала.
    # В JSON это дубль сообщения вперемешку с управляющими символами.
    "color_message",
})


class JsonFormatter(logging.Formatter):
    """
    Одна строка — один объект JSON.

    Время локальное Asia/Tashkent, как и везде в проекте: лог, в котором
    время не совпадает со временем записей в базе, при разборе инцидента
    только мешает.

    Сообщение форматируется как обычно, поэтому маскировка `telegram_id`
    (mask_user) продолжает работать: в JSON уезжает та же строка, что ушла бы
    в текстовый вывод, а не сырые аргументы.
    """

    def format(self, record: logging.LogRecord) -> str:
        import timeutils

        # Время со смещением, в отличие от базы. В базе оно намеренно наивное
        # (см. докстринг timeutils), но лог читают не только люди: сборщик
        # логов примет время без смещения за UTC и сдвинет всю картину
        # на пять часов — ровно тогда, когда по ней разбирают инцидент.
        payload = {
            "ts": timeutils.now().replace(tzinfo=timeutils.TZ).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        if record.exc_info:
            # Трассировка отдельным полем, а не внутри сообщения: иначе она
            # разорвёт строку на десяток и разрушит «одна строка — одна запись».
            payload["traceback"] = self.formatException(record.exc_info)

        for key, value in record.__dict__.items():
            if key not in _NOISE_FIELDS and not key.startswith("_"):
                payload[key] = value

        # default=str: в extra может попасть datetime или объект ORM,
        # и падение сериализации не должно съедать саму запись лога.
        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging(
    level: str | None = None,
    fmt: str | None = None,
    log_file: str | None = None,
    max_bytes: int = 10 * 1024 * 1024,
    backups: int = 5,
) -> None:
    """
    Настраивает корневой логгер. Зовётся один раз при старте процесса.

    Всё берётся из окружения, если не передано явно:
      LOG_LEVEL  — INFO по умолчанию;
      LOG_FORMAT — text (по умолчанию) или json;
      LOG_FILE   — если задан, добавляется файл с ротацией.

    Ротация нужна только для файла. В контейнере лог уходит в stdout,
    и его вращает сам Docker — второй механизм там только мешал бы.
    """
    level = (level or os.getenv("LOG_LEVEL") or "INFO").upper()
    fmt = (fmt or os.getenv("LOG_FORMAT") or "text").lower()
    log_file = log_file or os.getenv("LOG_FILE")

    formatter = (
        JsonFormatter()
        if fmt == "json"
        else logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )

    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.handlers.RotatingFileHandler(
            log_file, maxBytes=max_bytes, backupCount=backups, encoding="utf-8"
        ))

    for handler in handlers:
        handler.setFormatter(formatter)

    root = logging.getLogger()
    # Снимаем прежние обработчики: basicConfig и повторный вызов оставили бы
    # дубли, и каждая строка печаталась бы по нескольку раз.
    for existing in list(root.handlers):
        root.removeHandler(existing)
    for handler in handlers:
        root.addHandler(handler)
    root.setLevel(level)

    _adopt_foreign_loggers()


#: Логгеры, которые библиотеки настраивают себе сами, в обход корневого.
#: Uvicorn ставит на них собственные обработчики и отключает propagate —
#: его четыре строки о старте уходили бы текстом мимо нашего формата,
#: и «все логи в JSON» переставало быть правдой ровно там, где это
#: проверяет сборщик логов.
_FOREIGN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


def _adopt_foreign_loggers() -> None:
    for name in _FOREIGN_LOGGERS:
        logger = logging.getLogger(name)
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
        logger.propagate = True
