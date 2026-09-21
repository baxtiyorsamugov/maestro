"""
Панель мастера не должна содержать русского текста при language_code='uz'.

Проверяются собранные экраны, а не словари: перевод может лежать в texts
и не доезжать до пользователя, если вызывающий код не передал язык.
Ровно это и случилось с рендерами календаря — ключи были, экран оставался русским.

Отдельно ловим вторую ошибку того же рода: русский текст, оставшийся в коде
хендлеров вместо texts.py. Такой текст не переводится в принципе.
"""
import ast
import re
from pathlib import Path

import pytest

import constants
import presenters
import texts

CYRILLIC = re.compile(r"[а-яА-ЯёЁ]")
HANDLERS = Path(__file__).resolve().parent.parent / "handlers"
STYLIST_HANDLERS = HANDLERS / "stylist"
# Клиентская часть переведена позже (B-9.1) и закреплена тем же правилом:
# без теста инлайн-словари возвращались бы по одному, незаметно.
CHECKED_MODULES = sorted(
    str(p.relative_to(HANDLERS)).replace("\\", "/")
    for p in [*STYLIST_HANDLERS.glob("*.py"), *(HANDLERS / "client").glob("*.py"),
              HANDLERS / "fallback.py"]
    if p.stem != "__init__"
)


def russian_literals(path: Path) -> list[tuple[int, str]]:
    """Строковые литералы с кириллицей, кроме докстрингов."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = {
        ast.get_docstring(node, clean=False)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
    }
    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value not in docstrings
        and CYRILLIC.search(node.value)
    ]


class TestNoHardcodedRussian:
    @pytest.mark.parametrize("module", CHECKED_MODULES)
    def test_module_has_no_russian_literals(self, module):
        found = russian_literals(HANDLERS / module)
        assert found == [], (
            f"русский текст прямо в коде — он не переводится: "
            f"{[(line, value[:40]) for line, value in found]}"
        )


class TestRenderedScreens:
    """Собранные экраны на узбекском."""

    def _schedule(self, lang):
        import database as db

        schedule = db.Schedule(day_of_week=1, start_time="09:00", end_time="18:00")
        return presenters.build_schedule_overview_text("Aziz", {1: schedule}, [], lang=lang)

    def test_schedule_overview_uzbek_has_no_russian(self):
        assert not CYRILLIC.search(self._schedule("uz"))

    def test_schedule_overview_russian_still_russian(self):
        text = self._schedule("ru")
        assert CYRILLIC.search(text)
        assert "Понедельник" in text

    def test_special_dates_uzbek_has_no_russian(self):
        text = presenters.build_special_dates_text("Aziz", 2026, 10, [], lang="uz")
        assert not CYRILLIC.search(text)

    def test_special_date_detail_uzbek_has_no_russian(self):
        text = presenters.build_special_date_detail_text("2026-10-15", None, None, lang="uz")
        assert not CYRILLIC.search(text)

    def test_subscription_text_uzbek_has_no_russian(self):
        import database as db

        user = db.User(telegram_id=1, role="stylist", language_code="uz")
        assert not CYRILLIC.search(presenters.get_subscription_menu_text(user, "uz"))

    def test_non_stylist_subscription_text_uzbek(self):
        import database as db

        user = db.User(telegram_id=1, role="client", language_code="uz")
        assert not CYRILLIC.search(presenters.get_subscription_menu_text(user, "uz"))


class TestDayNames:
    @pytest.mark.parametrize("day", range(1, 8))
    def test_every_day_translated(self, day):
        assert not CYRILLIC.search(constants.day_name(day, "uz"))
        assert not CYRILLIC.search(constants.day_short(day, "uz"))

    def test_week_header_has_seven_days(self):
        header = constants.week_header("uz")
        assert len(header) == 7
        assert not CYRILLIC.search(" ".join(header))

    def test_russian_day_names_intact(self):
        assert constants.day_name(1, "ru") == "Понедельник"
        assert constants.day_name(7, "ru") == "Воскресенье"

    def test_unknown_language_falls_back_to_russian(self):
        assert constants.day_name(1, "de") == "Понедельник"


class TestPluralDays:
    """В русском числительное меняет форму слова, в узбекском — нет."""

    @pytest.mark.parametrize(
        ("count", "expected"),
        [(1, "день"), (2, "дня"), (4, "дня"), (5, "дней"),
         (11, "дней"), (21, "день"), (22, "дня"), (25, "дней"), (101, "день")],
    )
    def test_russian_forms(self, count, expected):
        assert presenters.plural_days(count, "ru") == expected

    @pytest.mark.parametrize("count", [1, 2, 5, 11, 21, 100])
    def test_uzbek_has_single_form(self, count):
        assert presenters.plural_days(count, "uz") == "kun"


class TestTextsCoverage:
    def test_no_key_missing_translation(self):
        missing = [
            f"{key}/{lang}"
            for key, translations in texts.TEXTS.items()
            for lang in texts.LANGUAGES
            if not str(translations.get(lang, "")).strip()
        ]
        assert missing == [], f"без перевода: {missing}"

    def test_placeholders_match_across_languages(self):
        """
        Несовпадение плейсхолдеров роняет format() в рантайме — на языке,
        который разработчик обычно не проверяет.
        """
        pattern = re.compile(r"\{(\w+)\}")
        mismatched = []
        for key, translations in texts.TEXTS.items():
            sets = {lang: set(pattern.findall(value)) for lang, value in translations.items()}
            if len(set(map(frozenset, sets.values()))) > 1:
                mismatched.append(f"{key}: {sets}")
        assert mismatched == [], f"разные плейсхолдеры: {mismatched}"
