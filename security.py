"""
Пароли и защита входа в админку.

Хеширование через hashlib.scrypt из стандартной библиотеки: отдельная зависимость
здесь не нужна, а для PyInstaller-сборки каждый лишний пакет — это лишние грабли.
scrypt устойчив к перебору на GPU, параметры взяты из рекомендаций OWASP.

Формат хранения: scrypt$<n>$<r>$<p>$<соль hex>$<хеш hex>
"""
from __future__ import annotations

import hashlib
import logging
import secrets
import time
from dataclasses import dataclass, field

# Параметры scrypt. N — степень двойки, стоимость по памяти и времени.
SCRYPT_N = 2**15
SCRYPT_R = 8
SCRYPT_P = 1
SALT_BYTES = 16
KEY_BYTES = 32

# scrypt требует 128 * N * r байт = ровно 32 МиБ при текущих параметрах,
# а дефолтный лимит OpenSSL равен тем же 32 МиБ и упирается в него с запасом.
SCRYPT_MAXMEM = 64 * 1024 * 1024

PREFIX = "scrypt"


def hash_password(password: str) -> str:
    """Хеш пароля со случайной солью."""
    salt = secrets.token_bytes(SALT_BYTES)
    key = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=KEY_BYTES,
        maxmem=SCRYPT_MAXMEM,
    )
    return f"{PREFIX}${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${key.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """
    Проверка пароля против сохранённого хеша.

    Сравнение константное по времени: обычное == по хешам утекает информацию
    через время выполнения.
    """
    try:
        prefix, n_raw, r_raw, p_raw, salt_hex, key_hex = stored.split("$")
        if prefix != PREFIX:
            return False
        key = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=int(n_raw),
            r=int(r_raw),
            p=int(p_raw),
            dklen=len(bytes.fromhex(key_hex)),
            maxmem=SCRYPT_MAXMEM,
        )
    except (ValueError, TypeError, MemoryError):
        return False

    return secrets.compare_digest(key.hex(), key_hex)


def looks_like_hash(value: str) -> bool:
    return value.startswith(f"{PREFIX}$")


@dataclass
class LoginThrottle:
    """
    Ограничение попыток входа.

    Состояние в памяти процесса: для одного инстанса админки этого достаточно,
    и это несравнимо лучше, чем отсутствие защиты. При переходе на несколько
    процессов счётчик надо будет вынести в Redis.
    """

    max_attempts: int = 5
    lockout_seconds: int = 300
    _attempts: dict[str, list[float]] = field(default_factory=dict)
    _locked_until: dict[str, float] = field(default_factory=dict)

    def is_locked(self, key: str) -> int:
        """Сколько секунд осталось до разблокировки. 0 — не заблокирован."""
        until = self._locked_until.get(key, 0)
        remaining = int(until - time.monotonic())
        if remaining <= 0:
            self._locked_until.pop(key, None)
            return 0
        return remaining

    def register_failure(self, key: str) -> int:
        """Регистрирует неудачную попытку. Возвращает число оставшихся попыток."""
        now = time.monotonic()
        window_start = now - self.lockout_seconds
        attempts = [t for t in self._attempts.get(key, []) if t > window_start]
        attempts.append(now)
        self._attempts[key] = attempts

        if len(attempts) >= self.max_attempts:
            self._locked_until[key] = now + self.lockout_seconds
            self._attempts.pop(key, None)
            logging.warning(
                "admin.login_locked key=%s seconds=%s", key, self.lockout_seconds
            )
            return 0

        return self.max_attempts - len(attempts)

    def reset(self, key: str) -> None:
        self._attempts.pop(key, None)
        self._locked_until.pop(key, None)
