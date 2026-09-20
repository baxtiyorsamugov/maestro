"""
Тесты резервного копирования (docs/ROADMAP.md, Фаза 6).

Полный цикл «снять дамп — потерять базу — восстановиться» прогнан вживую
на PostgreSQL в контейнере и описан в docs/DEPLOY.md. Здесь закрепляется
то, что можно проверить без живой базы и что легко сломать незаметно.

Главное из этого — ротация. Ошибка в ней не роняет ничего: бэкапы
продолжают сниматься, просто однажды окажется, что хранится не четырнадцать
копий, а одна, или что старые не удаляются и диск кончился. Узнать об этом
в момент аварии — худший из возможных способов.
"""
import gzip
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from backup_db import (
    DEFAULT_KEEP,
    BackupError,
    backup_name,
    make_backup,
    pg_command,
    stale_backups,
)


class FakeSettings:
    def __init__(self, url, host="db", port=5432, user="maestro",
                 password="secret", name="maestro"):
        self.url = url
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.name = name


class TestNaming:
    def test_name_sorts_chronologically(self):
        """
        Имя несёт дату так, чтобы сортировка по алфавиту совпадала
        с сортировкой по времени: на этом держится ротация.
        """
        older = backup_name(datetime(2026, 9, 20, 3, 0, 0))
        newer = backup_name(datetime(2026, 9, 21, 3, 0, 0))

        assert older < newer

    def test_same_day_different_time_still_sorts(self):
        morning = backup_name(datetime(2026, 9, 20, 3, 0, 0))
        evening = backup_name(datetime(2026, 9, 20, 21, 0, 0))

        assert morning < evening

    def test_suffix_is_kept(self):
        assert backup_name(datetime(2026, 9, 20), suffix=".db.gz").endswith(".db.gz")


class TestRotation:
    def _files(self, count):
        return [Path(f"maestro-202609{day:02d}-030000.sql.gz") for day in range(1, count + 1)]

    def test_keeps_the_newest(self):
        doomed = {p.name for p in stale_backups(self._files(10), keep=3)}

        assert doomed == {
            f"maestro-202609{day:02d}-030000.sql.gz" for day in range(1, 8)
        }

    def test_newest_are_not_touched(self):
        files = self._files(10)
        doomed = {p.name for p in stale_backups(files, keep=3)}

        survivors = [p.name for p in files if p.name not in doomed]
        assert survivors == [
            "maestro-20260908-030000.sql.gz",
            "maestro-20260909-030000.sql.gz",
            "maestro-20260910-030000.sql.gz",
        ]

    def test_nothing_to_delete_when_below_limit(self):
        assert stale_backups(self._files(3), keep=14) == []

    def test_zero_keeps_everything(self):
        """
        keep=0 — это «не удалять», а не «удалить всё».

        Обратное прочтение стоило бы всех копий разом, и именно такую
        опечатку в cron заметить труднее всего.
        """
        assert stale_backups(self._files(5), keep=0) == []

    def test_negative_keeps_everything_too(self):
        assert stale_backups(self._files(5), keep=-1) == []

    def test_order_of_input_does_not_matter(self):
        files = self._files(5)
        shuffled = [files[2], files[0], files[4], files[1], files[3]]

        assert stale_backups(shuffled, keep=2) == stale_backups(files, keep=2)

    def test_default_keeps_two_weeks(self):
        assert DEFAULT_KEEP == 14


class TestDockerCommand:
    """
    Запуск внутри контейнера — не удобство. При развёртывании через compose
    клиента PostgreSQL на хосте обычно нет вовсе, а в образе базы он есть
    и той же версии, что сервер.
    """

    def test_without_docker_command_is_unchanged(self):
        settings = FakeSettings("postgresql+asyncpg://...")
        command, _ = pg_command(settings, ["pg_dump", "--host", "db"], None)

        assert command == ["pg_dump", "--host", "db"]

    def test_with_docker_command_is_wrapped(self):
        settings = FakeSettings("postgresql+asyncpg://...")
        command, _ = pg_command(settings, ["pg_dump", "--host", "db"], "db")

        assert command[:4] == ["docker", "compose", "exec", "-T"]
        assert "pg_dump" in command

    def test_host_becomes_localhost_inside_the_container(self):
        """Внутри контейнера сервер — это localhost, а не имя сервиса."""
        settings = FakeSettings("postgresql+asyncpg://...")
        command, _ = pg_command(settings, ["pg_dump", "--host", "db", "--port", "5432"], "db")

        assert command[command.index("--host") + 1] == "localhost"
        assert command[command.index("--port") + 1] == "5432", "порт трогать не должны"

    def test_password_goes_through_environment(self):
        """Аргументы процесса видны в `ps` любому пользователю машины."""
        settings = FakeSettings("postgresql+asyncpg://...", password="sup3rs3cret")
        command, env = pg_command(settings, ["pg_dump"], None)

        assert "sup3rs3cret" not in " ".join(command)
        assert env["PGPASSWORD"] == "sup3rs3cret"


class TestUnsupportedDatabase:
    def test_mysql_says_so_plainly(self, tmp_path, monkeypatch):
        import config

        monkeypatch.setattr(
            config, "load_database_settings",
            lambda: FakeSettings("mysql+aiomysql://maestro:pass@db:3306/maestro"),
        )

        with pytest.raises(BackupError, match="не реализован"):
            make_backup(tmp_path)


class TestSqliteBackup:
    def test_snapshot_is_made_and_gzipped(self, tmp_path, monkeypatch):
        """
        SQLite копируется не обычным cp: копия файла под нагрузкой может
        застать базу посреди транзакции. Встроенный backup API делает
        согласованный снимок.
        """
        import sqlite3

        import config

        source = tmp_path / "live.db"
        connection = sqlite3.connect(source)
        connection.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
        connection.execute("INSERT INTO users (name) VALUES ('Гульнора')")
        connection.commit()
        connection.close()

        monkeypatch.setattr(
            config, "load_database_settings",
            lambda: FakeSettings(f"sqlite+aiosqlite:///{source}", name=str(source)),
        )

        created = make_backup(tmp_path / "out")

        assert created.exists()
        assert created.name.endswith(".db.gz")

        restored = tmp_path / "restored.db"
        restored.write_bytes(gzip.open(created, "rb").read())
        check = sqlite3.connect(restored)
        try:
            name = check.execute("SELECT name FROM users").fetchone()[0]
        finally:
            check.close()
        assert name == "Гульнора", "данные не пережили копирование"

    def test_missing_file_is_reported(self, tmp_path, monkeypatch):
        import config

        monkeypatch.setattr(
            config, "load_database_settings",
            lambda: FakeSettings(
                "sqlite+aiosqlite:///nope.db", name=str(tmp_path / "nope.db")
            ),
        )

        with pytest.raises(BackupError, match="не найден"):
            make_backup(tmp_path / "out")

    def test_rotation_runs_after_backup(self, tmp_path, monkeypatch):
        import sqlite3

        import config

        source = tmp_path / "live.db"
        connection = sqlite3.connect(source)
        connection.execute("CREATE TABLE t (id INTEGER)")
        connection.commit()
        connection.close()

        monkeypatch.setattr(
            config, "load_database_settings",
            lambda: FakeSettings(f"sqlite+aiosqlite:///{source}", name=str(source)),
        )

        out = tmp_path / "out"
        out.mkdir()
        for day in range(1, 6):
            (out / f"maestro-202601{day:02d}-030000.db.gz").write_bytes(b"old")

        make_backup(out, keep=2)

        assert len(list(out.glob("maestro-*.gz"))) == 2
