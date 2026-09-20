"""
Тесты вывода логов (docs/ROADMAP.md, Фазы 3 и 6).

Логи писались строкой «время уровень имя: сообщение». Человеку читать удобно,
машине — нет: чтобы собрать все строки одного апдейта, приходилось придумывать
регулярки под собственный же формат.

Три вещи, которые здесь закрепляются и каждая из которых ломается тихо.

1. Одна строка — один разбираемый объект. Трассировка, попавшая внутрь
   сообщения, разрывает запись на десяток строк, и весь смысл JSON пропадает.
2. Время со смещением. В базе оно намеренно наивное, но лог читает ещё
   и сборщик: время без смещения он примет за UTC и сдвинет всю картину
   на пять часов — ровно тогда, когда по ней разбирают инцидент.
3. Маскировка `telegram_id` переживает смену формата. JSON, в который уехали
   бы сырые аргументы вместо готового сообщения, вернул бы в логи всё то,
   что из них убирали (CLAUDE.md, 4.4).
"""
import io
import json
import logging

import logutil
import timeutils


def _capture(fmt="json", level="INFO", **kwargs) -> io.StringIO:
    logutil.setup_logging(level=level, fmt=fmt, **kwargs)
    buffer = io.StringIO()
    logging.getLogger().handlers[0].stream = buffer
    return buffer


def _lines(buffer: io.StringIO) -> list[dict]:
    return [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]


class TestJsonOutput:
    def test_one_line_is_one_object(self):
        buffer = _capture()
        logging.getLogger("proba").info("update.done id=%s", 42)

        records = _lines(buffer)
        assert len(records) == 1
        assert records[0]["message"] == "update.done id=42"

    def test_required_fields_are_present(self):
        buffer = _capture()
        logging.getLogger("proba").warning("что-то не так")

        record = _lines(buffer)[0]
        for field in ("ts", "level", "logger", "message"):
            assert field in record, f"нет поля {field}"
        assert record["level"] == "WARNING"
        assert record["logger"] == "proba"

    def test_extra_fields_become_json_fields(self):
        """logging.info(..., extra={...}) должен работать сам собой."""
        buffer = _capture()
        logging.getLogger("proba").info("есть контекст", extra={"update_id": 7})

        assert _lines(buffer)[0]["update_id"] == 7

    def test_unserialisable_extra_does_not_eat_the_record(self):
        """
        В extra может попасть объект ORM или datetime. Падение сериализации
        не должно съедать саму запись: лог нужен именно тогда, когда что-то
        идёт не так.
        """
        buffer = _capture()
        logging.getLogger("proba").info("объект", extra={"obj": object()})

        assert len(_lines(buffer)) == 1

    def test_cyrillic_is_not_escaped(self):
        """\\u0447\\u0442\\u043e вместо «что» делает лог нечитаемым."""
        buffer = _capture()
        logging.getLogger("proba").info("запись отменена")

        assert "запись отменена" in buffer.getvalue()


class TestTracebacks:
    def test_traceback_goes_to_its_own_field(self):
        buffer = _capture()
        try:
            raise ValueError("бум")
        except ValueError:
            logging.getLogger("proba").exception("handler.unhandled_error")

        record = _lines(buffer)[0]
        assert "ValueError" in record["traceback"]

    def test_traceback_does_not_break_the_line(self):
        """
        Трассировка внутри сообщения разорвала бы запись на десяток строк,
        и «одна строка — одна запись» перестало бы выполняться.
        """
        buffer = _capture()
        try:
            raise ValueError("бум")
        except ValueError:
            logging.getLogger("proba").exception("сломалось")

        assert len(_lines(buffer)) == 1
        assert "Traceback" not in _lines(buffer)[0]["message"]


class TestTimestamp:
    def test_offset_is_explicit(self):
        """Без смещения сборщик логов примет время за UTC."""
        buffer = _capture()
        logging.getLogger("proba").info("время")

        assert "+05:00" in _lines(buffer)[0]["ts"]

    def test_wall_clock_matches_the_database(self):
        """
        Лог, в котором время не совпадает со временем записей в базе,
        при разборе инцидента только мешает.
        """
        buffer = _capture()
        logging.getLogger("proba").info("время")

        assert _lines(buffer)[0]["ts"][:16] == timeutils.now().isoformat()[:16]


class TestMaskingSurvivesTheFormat:
    def test_masked_id_reaches_json(self):
        buffer = _capture()
        logging.getLogger("proba").info(
            "access.denied user=%s", logutil.mask_user(123456789)
        )

        assert logutil.mask_user(123456789) in buffer.getvalue()

    def test_raw_id_does_not_leak_through_arguments(self):
        """
        JSON, в который уехали бы сырые args вместо готового сообщения,
        вернул бы в логи всё то, что из них убирали.
        """
        buffer = _capture()
        logging.getLogger("proba").info(
            "access.denied user=%s", logutil.mask_user(123456789)
        )

        assert "123456789" not in buffer.getvalue()


class TestTextFormatStillWorks:
    def test_default_is_human_readable(self):
        """
        JSON в терминале при локальной разработке читать невозможно,
        поэтому по умолчанию остаётся текст.
        """
        logutil.setup_logging(fmt="text")
        buffer = io.StringIO()
        logging.getLogger().handlers[0].stream = buffer

        logging.getLogger("proba").info("обычная строка")

        output = buffer.getvalue()
        assert "обычная строка" in output
        assert not output.strip().startswith("{")


class TestHandlers:
    def test_repeated_setup_does_not_duplicate_output(self):
        """
        Повторный вызов оставил бы старые обработчики, и каждая строка
        печаталась бы по нескольку раз.
        """
        logutil.setup_logging(fmt="json")
        logutil.setup_logging(fmt="json")

        assert len(logging.getLogger().handlers) == 1

    def test_file_handler_rotates(self, tmp_path):
        """
        Ротация нужна только для файла: в контейнере лог уходит в stdout,
        и его вращает сам Docker.
        """
        log_file = tmp_path / "logs" / "maestro.log"
        logutil.setup_logging(fmt="json", log_file=str(log_file), max_bytes=500, backups=2)

        for index in range(200):
            logging.getLogger("proba").info("строка номер %s с запасом текста", index)

        for handler in logging.getLogger().handlers:
            handler.close()

        produced = sorted(p.name for p in log_file.parent.iterdir())
        assert log_file.exists()
        assert len(produced) > 1, f"ротация не сработала: {produced}"
        assert len(produced) <= 3, f"старые файлы не удаляются: {produced}"

    def test_level_is_respected(self):
        buffer = _capture(level="WARNING")
        logging.getLogger("proba").info("не должно попасть")
        logging.getLogger("proba").warning("должно попасть")

        records = _lines(buffer)
        assert len(records) == 1
        assert records[0]["level"] == "WARNING"


def teardown_module():
    """Возвращаем обычный вывод: иначе остальные тесты пишут в JSON."""
    logutil.setup_logging(fmt="text")
