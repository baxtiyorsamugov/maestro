"""
Проверка, что бэкап действительно восстанавливается.

Бэкап, из которого никто не пробовал восстановиться, бэкапом не является:
он превращается в файл, про который все уверены, что он поможет. Узнать,
что это не так, в момент аварии — худший из возможных способов.

Скрипт разворачивает дамп во **временную** базу рядом с боевой, сверяет
число строк в ключевых таблицах и удаляет временную базу за собой.
Боевая база при этом не трогается вовсе.

    python scripts/verify_backup.py backups/maestro-20260920-030000.sql.gz

Код возврата 0 — восстановление прошло и данные сошлись. Всё остальное —
повод разобраться до того, как понадобится по-настоящему.
"""
import argparse
import gzip
import os
import subprocess
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backup_db import pg_command

import config

#: Таблицы, по которым сверяем. Не все подряд: смысл проверки в том,
#: что вернулись данные, ради которых базу и держат.
CHECKED_TABLES = ("users", "stylists", "bookings", "services", "audit_log")


class VerifyError(RuntimeError):
    pass


def _psql_env(settings) -> dict:
    env = dict(os.environ)
    if settings.password:
        # Как и в backup_db.py: аргументы процесса видны в `ps`.
        env["PGPASSWORD"] = settings.password
    return env


def _psql(settings, dbname: str, sql: str, env: dict, docker_service: str | None = None) -> str:
    command, env = pg_command(settings, [
        "psql",
        "--host", settings.host,
        "--port", str(settings.port),
        "--username", settings.user,
        "--dbname", dbname,
        "--no-align", "--tuples-only",
        "--command", sql,
    ], docker_service)
    result = subprocess.run(command, capture_output=True, env=env, check=False)
    if result.returncode != 0:
        raise VerifyError(
            f"psql: {result.stderr.decode('utf-8', 'replace').strip()[:400]}"
        )
    return result.stdout.decode("utf-8", "replace").strip()


def _row_counts(settings, dbname: str, env: dict, docker_service=None) -> dict[str, int]:
    counts = {}
    for table in CHECKED_TABLES:
        # to_regclass возвращает NULL, если таблицы нет: дамп мог быть снят
        # до появления таблицы, и падать из-за этого незачем.
        exists = _psql(
            settings, dbname, f"SELECT to_regclass('public.{table}')", env, docker_service
        )
        if not exists:
            continue
        counts[table] = int(
            _psql(settings, dbname, f"SELECT count(*) FROM {table}", env, docker_service)
        )
    return counts


def verify(dump_path: Path, docker_service: str | None = None) -> dict:
    settings = config.load_database_settings()
    if not settings.url.startswith("postgresql"):
        raise VerifyError(
            "проверка написана для PostgreSQL. Для SQLite достаточно распаковать "
            "копию и открыть её: sqlite3 копия.db 'PRAGMA integrity_check;'"
        )
    if not dump_path.exists():
        raise VerifyError(f"файл не найден: {dump_path}")

    env = _psql_env(settings)
    scratch = f"maestro_verify_{uuid.uuid4().hex[:8]}"

    live_counts = _row_counts(settings, settings.name, env, docker_service)

    # Временную базу создаём из postgres: нельзя создать базу, находясь в ней.
    _psql(settings, "postgres", f'CREATE DATABASE "{scratch}"', env, docker_service)
    try:
        restore_command, restore_env = pg_command(settings, [
            "psql",
            "--host", settings.host,
            "--port", str(settings.port),
            "--username", settings.user,
            "--dbname", scratch,
            # Останавливаемся на первой же ошибке: дамп, развернувшийся
            # наполовину, хуже не развернувшегося — он выглядит рабочим.
            "--set", "ON_ERROR_STOP=1",
            "--quiet",
        ], docker_service)
        with gzip.open(dump_path, "rb") as archive:
            restore = subprocess.run(
                restore_command,
                input=archive.read(), capture_output=True, env=restore_env, check=False,
            )
        if restore.returncode != 0:
            raise VerifyError(
                "восстановление не прошло: "
                + restore.stderr.decode("utf-8", "replace").strip()[:600]
            )

        restored_counts = _row_counts(settings, scratch, env, docker_service)
    finally:
        _psql(settings, "postgres", f'DROP DATABASE IF EXISTS "{scratch}"', env, docker_service)

    return {"live": live_counts, "restored": restored_counts}


def main() -> int:
    parser = argparse.ArgumentParser(description="Проверка восстановления бэкапа")
    parser.add_argument("dump", help="путь к файлу .sql.gz")
    parser.add_argument(
        "--docker-service",
        help="работать внутри контейнера compose (обычно db)",
    )
    args = parser.parse_args()

    try:
        result = verify(Path(args.dump), args.docker_service)
    except VerifyError as exc:
        print(f"Проверка не прошла: {exc}", file=sys.stderr)
        return 1

    live, restored = result["live"], result["restored"]
    if not restored:
        print("В восстановленной базе нет ни одной из проверяемых таблиц.", file=sys.stderr)
        return 1

    print(f"{'таблица':<14} {'в базе':>8} {'из бэкапа':>10}")
    mismatched = []
    for table in sorted(restored):
        here, there = live.get(table, 0), restored[table]
        mark = "" if here == there else "  <-- расходится"
        if here != there:
            mismatched.append(table)
        print(f"{table:<14} {here:>8} {there:>10}{mark}")

    if mismatched:
        # Расхождение — не обязательно беда: между снятием дампа и проверкой
        # в базу могли добавиться строки. Но сказать об этом надо прямо,
        # чтобы человек посмотрел на даты, а не отмахнулся.
        print(
            "\nЧисла разошлись. Это нормально, если после снятия дампа в базу "
            "успели записать; проверьте время файла.",
            file=sys.stderr,
        )
        return 2

    print("\nВосстановление прошло, данные сошлись.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
