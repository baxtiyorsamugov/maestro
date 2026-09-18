"""
Генерация хеша пароля для админки.

Пароль в .env не должен лежать открытым текстом: любой, кто получит доступ
к файлу или к копии дистрибутива, сразу получает доступ к панели.

Использование:
    python scripts/hash_password.py
    python scripts/hash_password.py --password 'мой пароль'

Полученную строку положите в .env как ADMIN_PASSWORD.
"""
import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import security

MIN_LENGTH = 12


def main() -> int:
    parser = argparse.ArgumentParser(description="Хеш пароля для ADMIN_PASSWORD")
    parser.add_argument(
        "--password",
        help="пароль; без этого флага будет запрошен скрыто, что безопаснее — "
             "пароль не попадёт в историю команд",
    )
    parser.add_argument(
        "--allow-weak",
        action="store_true",
        help=f"разрешить пароль короче {MIN_LENGTH} символов",
    )
    args = parser.parse_args()

    password = args.password
    if not password:
        password = getpass.getpass("Пароль: ")
        if password != getpass.getpass("Повторите: "):
            print("Пароли не совпадают")
            return 1

    if not password:
        print("Пустой пароль")
        return 1

    if len(password) < MIN_LENGTH and not args.allow_weak:
        print(f"Пароль короче {MIN_LENGTH} символов. Возьмите длиннее или --allow-weak.")
        return 1

    hashed = security.hash_password(password)
    if not security.verify_password(password, hashed):
        print("Внутренняя ошибка: хеш не проверяется")
        return 1

    print("\nСтрока для .env:\n")
    print(f"ADMIN_PASSWORD={hashed}")
    print("\nПосле замены перезапустите админку. Открытый пароль из .env удалите.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
