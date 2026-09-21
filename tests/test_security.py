"""
Тесты хеширования пароля и защиты входа (docs/AUDIT.md, B-6).
"""
import time

import pytest

import security


class TestPasswordHashing:
    def test_hash_verifies_against_original(self):
        hashed = security.hash_password("правильный пароль")
        assert security.verify_password("правильный пароль", hashed)

    def test_wrong_password_rejected(self):
        hashed = security.hash_password("правильный пароль")
        assert not security.verify_password("неправильный", hashed)

    def test_empty_password_rejected(self):
        hashed = security.hash_password("что-то")
        assert not security.verify_password("", hashed)

    def test_same_password_gives_different_hashes(self):
        """Соль случайная: одинаковые пароли не должны давать одинаковый хеш."""
        first = security.hash_password("пароль")
        second = security.hash_password("пароль")
        assert first != second
        assert security.verify_password("пароль", first)
        assert security.verify_password("пароль", second)

    def test_hash_does_not_contain_password(self):
        hashed = security.hash_password("совершенно-секретно")
        assert "совершенно-секретно" not in hashed

    def test_unicode_password_works(self):
        hashed = security.hash_password("пароль-с-кириллицей-и-🔑")
        assert security.verify_password("пароль-с-кириллицей-и-🔑", hashed)

    @pytest.mark.parametrize("broken", ["", "мусор", "scrypt$плохо", "bcrypt$1$2$3$4$5", "$$$$$"])
    def test_malformed_hash_rejected_without_raising(self, broken):
        assert not security.verify_password("любой", broken)

    def test_looks_like_hash(self):
        assert security.looks_like_hash(security.hash_password("x"))
        assert not security.looks_like_hash("обычный-пароль")
        assert not security.looks_like_hash("")


class TestLoginThrottle:
    def test_allows_attempts_below_limit(self):
        throttle = security.LoginThrottle(max_attempts=3)
        assert throttle.register_failure("1.2.3.4") == 2
        assert throttle.register_failure("1.2.3.4") == 1
        assert throttle.is_locked("1.2.3.4") == 0

    def test_locks_after_limit(self):
        throttle = security.LoginThrottle(max_attempts=3, lockout_seconds=60)
        for _ in range(3):
            throttle.register_failure("1.2.3.4")
        assert throttle.is_locked("1.2.3.4") > 0

    def test_lock_is_per_client(self):
        throttle = security.LoginThrottle(max_attempts=2)
        throttle.register_failure("1.1.1.1")
        throttle.register_failure("1.1.1.1")
        assert throttle.is_locked("1.1.1.1") > 0
        assert throttle.is_locked("2.2.2.2") == 0

    def test_successful_login_resets_counter(self):
        throttle = security.LoginThrottle(max_attempts=3)
        throttle.register_failure("1.2.3.4")
        throttle.register_failure("1.2.3.4")
        throttle.reset("1.2.3.4")
        assert throttle.register_failure("1.2.3.4") == 2

    def test_lock_expires(self):
        throttle = security.LoginThrottle(max_attempts=1, lockout_seconds=0)
        throttle.register_failure("1.2.3.4")
        time.sleep(0.01)
        assert throttle.is_locked("1.2.3.4") == 0


class TestConstantTimeEquals:
    """
    Сравнение, безопасное для не-ASCII.

    `secrets.compare_digest` на объектах `str` требует, чтобы оба были только
    из ASCII, и иначе бросает TypeError. В форме входа это означало бы, что
    кириллический пароль роняет панель пятисоткой вместо того, чтобы получить
    отказ — а аудитория здесь пишет по-русски и по-узбекски.
    """

    def test_equal_ascii(self):
        assert security.constant_time_equals("secret", "secret") is True

    def test_different_ascii(self):
        assert security.constant_time_equals("secret", "другой"[:6]) is False

    def test_cyrillic_does_not_raise(self):
        assert security.constant_time_equals("пароль", "мимо") is False

    def test_equal_cyrillic(self):
        assert security.constant_time_equals("пароль", "пароль") is True

    def test_mixed_alphabets(self):
        assert security.constant_time_equals("owner", "владелец") is False

    def test_empty_strings(self):
        assert security.constant_time_equals("", "") is True
        assert security.constant_time_equals("", "x") is False

    def test_emoji_does_not_raise(self):
        """Любой символ вне ASCII ломал бы сравнение одинаково."""
        assert security.constant_time_equals("🔑", "🔑") is True
