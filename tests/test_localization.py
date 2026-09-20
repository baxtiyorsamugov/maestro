"""
Тесты локализации панели мастера (docs/AUDIT.md, B-9).

Панель мастера была только на русском: узбекоязычный мастер видел смесь языков
в своём же рабочем интерфейсе, а приветствие печаталось сразу на двух.

Главная ловушка тут структурная. Фильтр хендлера сравнивает текст сообщения
с подписью кнопки буквально. Переведёшь кнопку, не тронув фильтр — и хендлер
перестанет срабатывать: без ошибки, без записи в логах, просто кнопка не работает.
Поэтому проверяем, что каждая кнопка панели покрыта фильтром на обоих языках.
"""
import re
from pathlib import Path

import pytest

import handlers
import texts

HANDLERS_DIR = Path(__file__).resolve().parent.parent / "handlers"


class TestStylistButtons:
    def test_every_button_has_both_languages(self):
        missing = [
            f"{key}/{lang}"
            for key, translations in texts.STYLIST_BUTTONS.items()
            for lang in texts.LANGUAGES
            if not str(translations.get(lang, "")).strip()
        ]
        assert missing == [], f"нет перевода: {missing}"

    def test_languages_differ(self):
        """Скопированный русский текст в поле uz — это не перевод."""
        same = [
            key for key, tr in texts.STYLIST_BUTTONS.items()
            if tr["ru"] == tr["uz"]
        ]
        assert same == [], f"узбекский совпадает с русским: {same}"

    @pytest.mark.parametrize("key", sorted(texts.STYLIST_BUTTONS))
    def test_all_variants_returns_every_language(self, key):
        variants = texts.all_variants(key)
        assert len(variants) == len(texts.LANGUAGES)
        assert all(v.strip() for v in variants)

    def test_all_variants_works_for_client_buttons_too(self):
        assert len(texts.all_variants("my_profile")) == len(texts.LANGUAGES)

    def test_all_variants_of_unknown_key_is_empty(self):
        assert texts.all_variants("такого-ключа-нет") == []


class TestHandlerFilters:
    """
    Фильтр на буквальном сравнении с русской строкой — это отложенная поломка.
    Такие фильтры не должны появляться заново.
    """

    def test_no_literal_russian_text_filters(self):
        pattern = re.compile(r'F\.text\s*==\s*"[^"]*[а-яА-ЯёЁ]')
        offenders = []
        for path in HANDLERS_DIR.rglob("*.py"):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if pattern.search(line):
                    offenders.append(f"{path.name}:{number}")
        assert offenders == [], (
            "фильтр сравнивает текст с одним языком — кнопка сломается "
            f"после переключения: {offenders}. Используйте texts.all_variants()"
        )

    def test_stylist_panel_buttons_are_reachable(self):
        """
        Каждая кнопка панели должна ловиться каким-нибудь фильтром.
        Иначе она просто ничего не делает.
        """
        sources = "\n".join(
            path.read_text(encoding="utf-8") for path in HANDLERS_DIR.rglob("*.py")
        )
        unreachable = [
            key for key in texts.STYLIST_BUTTONS
            if f'all_variants("{key}")' not in sources
        ]
        assert unreachable == [], f"кнопки без фильтра: {unreachable}"


class TestPanelTexts:
    @pytest.mark.parametrize(
        "key",
        ["panel_welcome", "panel_exited", "portfolio_prompt",
         "portfolio_photo_added", "portfolio_done"],
    )
    def test_panel_text_exists_in_both_languages(self, key):
        for lang in texts.LANGUAGES:
            value = texts.get_text(key, lang)
            assert value != "Text not found", f"{key}/{lang}"
            assert value.strip()

    def test_welcome_shows_one_language_at_a_time(self):
        """Раньше приветствие печаталось сразу на двух языках."""
        russian = texts.get_text("panel_welcome", "ru")
        uzbek = texts.get_text("panel_welcome", "uz")
        assert "xush kelibsiz" not in russian
        assert "Добро пожаловать" not in uzbek

    def test_portfolio_prompt_has_count_placeholder(self):
        for lang in texts.LANGUAGES:
            assert "{count}" in texts.get_text("portfolio_prompt", lang)


class TestRoutersStillAssemble:
    def test_routers_unchanged_by_localization(self):
        assert len(handlers.ROUTERS) == 15
