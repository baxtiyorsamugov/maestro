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
import os
from functools import lru_cache

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
