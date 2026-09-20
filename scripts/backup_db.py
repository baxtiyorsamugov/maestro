"""
Резервная копия базы.

Запускается по расписанию (cron на сервере, планировщик в Windows) и кладёт
свежий дамп в каталог бэкапов, удаляя самые старые.

Формат — обычный SQL под gzip, а не кастомный формат pg_dump. Восстановление
из кастомного формата требует pg_restore подходящей версии и разбирательства
с флагами; обычный SQL разворачивается одной командой, которую можно набрать
руками в три часа ночи, и его содержимое видно глазами. Для базы этого размера
выигрыш кастомного формата не стоит этой разницы.

Пароль передаётся через PGPASSWORD, а не в командной строке: аргументы процесса
видны всем в `ps`.

    python scripts/backup_db.py                    # в ./backups
    python scripts/backup_db.py --out /var/backups --keep 30

Восстановление описано в docs/DEPLOY.md и проверяется scripts/verify_backup.py —
бэкап, из которого никто не пробовал восстановиться, бэкапом не является.
"""
import argparse
import gzip
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
import timeutils

DEFAULT_DIR = "backups"
DEFAULT_KEEP = 14

#: Имя файла: сортировка по алфавиту совпадает с сортировкой по времени,
#: поэтому ротация — это просто «отрезать хвост отсортированного списка».
NAME_FORMAT = "maestro-%Y%m%d-%H%M%S"


class BackupError(RuntimeError):
    pass


def backup_name(moment: datetime | None = None, suffix: str = ".sql.gz") -> str:
    return (moment or timeutils.now()).strftime(NAME_FORMAT) + suffix


def stale_backups(existing: list[Path], keep: int) -> list[Path]:
    """
    Какие файлы удалить, оставив `keep` самых свежих.

    Сортируем по имени, а не по времени файла: время файла меняется при
    копировании каталога, а имя несёт дату снятия дампа.
    """
    if keep <= 0:
        return []
    ordered = sorted(existing, key=lambda path: path.name, reverse=True)
    return ordered[keep:]


def pg_command(settings, args: list[str], docker_service: str | None) -> tuple[list[str], dict]:
    """
    Команда к PostgreSQL — на хосте или внутри контейнера.

    docker_service нужен не для удобства. При развёртывании через compose
    клиента PostgreSQL на хосте обычно нет вовсе, а в образе postgres он есть
    и, что важнее, той же версии, что и сервер: pg_dump старше сервера
    отказывается работать, и узнать об этом в момент аварии — плохой план.

    Пароль уходит переменной окружения: аргументы процесса видны в `ps`.
    """
    env = dict(os.environ)
    if settings.password:
        env["PGPASSWORD"] = settings.password

    if not docker_service:
        return args, env

    # Внутри контейнера сервер — это localhost: имя сервиса compose тут
    # лишняя зависимость от DNS, а ходим мы к самим себе.
    localised = [
        "localhost" if index and args[index - 1] == "--host" else value
        for index, value in enumerate(args)
    ]
    prefix = [
        "docker", "compose", "exec", "-T",
        "--env", f"PGPASSWORD={settings.password or ''}",
        docker_service,
    ]
    return prefix + localised, env


def _dump_postgres(settings, target: Path, docker_service: str | None = None) -> None:
    if not docker_service and not shutil.which("pg_dump"):
        raise BackupError(
            "pg_dump не найден. При развёртывании через compose клиент есть "
            "в контейнере базы: запустите с --docker-service db "
            "(подробности — docs/DEPLOY.md)"
        )

    command, env = pg_command(settings, [
        "pg_dump",
        "--host", settings.host,
        "--port", str(settings.port),
        "--username", settings.user,
        "--dbname", settings.name,
        # Без владельца и прав: дамп должен разворачиваться и в базу,
        # где роль называется иначе, — иначе восстановление на новом
        # сервере упирается в «role does not exist».
        "--no-owner",
        "--no-acl",
    ], docker_service)

    with gzip.open(target, "wb") as archive:
        process = subprocess.run(command, capture_output=True, env=env, check=False)
        if process.returncode != 0:
            raise BackupError(
                f"pg_dump завершился с кодом {process.returncode}: "
                f"{process.stderr.decode('utf-8', 'replace').strip()[:400]}"
            )
        archive.write(process.stdout)


def _dump_sqlite(settings, target: Path) -> None:
    """
    SQLite копируется файлом, но не обычным cp.

    Копия файла под нагрузкой может застать базу посреди транзакции.
    Встроенный backup API делает согласованный снимок, не блокируя пишущих.
    """
    import sqlite3

    source_path = Path(settings.name)
    if not source_path.exists():
        raise BackupError(f"файл базы не найден: {source_path}")

    snapshot = target.with_suffix("")
    source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
    destination = sqlite3.connect(snapshot)
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()

    with open(snapshot, "rb") as raw, gzip.open(target, "wb") as archive:
        shutil.copyfileobj(raw, archive)
    snapshot.unlink()


def make_backup(out_dir: Path, keep: int = DEFAULT_KEEP, docker_service: str | None = None) -> Path:
    settings = config.load_database_settings()
    out_dir.mkdir(parents=True, exist_ok=True)

    url = settings.url
    if url.startswith("postgresql"):
        target = out_dir / backup_name(suffix=".sql.gz")
        _dump_postgres(settings, target, docker_service)
    elif url.startswith("sqlite"):
        target = out_dir / backup_name(suffix=".db.gz")
        _dump_sqlite(settings, target)
    else:
        raise BackupError(
            f"бэкап для этой базы не реализован: {url.split('://')[0]}. "
            "Снимите дамп штатным средством драйвера."
        )

    if target.stat().st_size == 0:
        target.unlink()
        raise BackupError("дамп получился пустым — копия не сохранена")

    for old in stale_backups(list(out_dir.glob("maestro-*.gz")), keep):
        old.unlink()

    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="Резервная копия базы Maestro")
    parser.add_argument("--out", default=DEFAULT_DIR, help="каталог для копий")
    parser.add_argument(
        "--keep", type=int, default=DEFAULT_KEEP, help="сколько копий оставить"
    )
    parser.add_argument(
        "--docker-service",
        help="снять дамп внутри контейнера compose (обычно db): клиента "
             "PostgreSQL на хосте может не быть вовсе",
    )
    args = parser.parse_args()

    try:
        created = make_backup(Path(args.out), args.keep, args.docker_service)
    except BackupError as exc:
        # Печатаем в stderr и возвращаем ненулевой код: тихо упавший бэкап
        # обнаруживается в тот день, когда он нужен.
        print(f"Бэкап не сделан: {exc}", file=sys.stderr)
        return 1

    size_mb = created.stat().st_size / 1024 / 1024
    print(f"Готово: {created} ({size_mb:.2f} МБ)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
