"""
Тесты локализации.

Суррогатные пары — отдельная беда: строка вида "\\ud83d\\udeab" выглядит
в исходнике правдоподобно, проходит компиляцию, но в UTF-8 не кодируется
и уходит в Telegram мусором. Глазами такое не ловится, поэтому проверяем тестом.
"""
import texts


class TestCompleteness:
    def test_every_text_has_both_languages(self):
        missing = [
            f"{key}/{lang}"
            for key, translations in texts.TEXTS.items()
            for lang in texts.LANGUAGES
            if not str(translations.get(lang, "")).strip()
        ]
        assert missing == [], f"нет перевода: {missing}"

    def test_every_button_has_both_languages(self):
        missing = [
            f"{key}/{lang}"
            for key, translations in texts.BUTTONS.items()
            for lang in texts.LANGUAGES
            if not str(translations.get(lang, "")).strip()
        ]
        assert missing == [], f"нет перевода: {missing}"

    def test_button_sets_match_across_languages(self):
        assert set(texts.get_buttons("ru")) == set(texts.get_buttons("uz"))


class TestEncoding:
    def test_no_surrogates_in_texts(self):
        broken = [
            f"{key}/{lang}"
            for key, translations in texts.TEXTS.items()
            for lang, value in translations.items()
            if any(0xD800 <= ord(ch) <= 0xDFFF for ch in str(value))
        ]
        assert broken == [], f"суррогатные пары: {broken}"

    def test_no_surrogates_in_buttons(self):
        broken = [
            f"{key}/{lang}"
            for key, translations in texts.BUTTONS.items()
            for lang, value in translations.items()
            if any(0xD800 <= ord(ch) <= 0xDFFF for ch in str(value))
        ]
        assert broken == [], f"суррогатные пары: {broken}"

    def test_all_strings_encode_to_utf8(self):
        for key, translations in texts.TEXTS.items():
            for lang, value in translations.items():
                try:
                    str(value).encode("utf-8")
                except UnicodeEncodeError as e:
                    raise AssertionError(f"{key}/{lang} не кодируется: {e}") from e


class TestLookup:
    def test_known_key_returns_translation(self):
        assert texts.get_text("status_pending", "ru") != "Text not found"
        assert texts.get_text("status_pending", "uz") != "Text not found"

    def test_unknown_key_is_reported(self):
        assert texts.get_text("такого_ключа_нет", "ru") == "Text not found"

    def test_unknown_language_falls_back_to_russian(self):
        assert texts.get_text("status_pending", "de") == texts.get_text("status_pending", "ru")

    def test_cancelled_status_is_present(self):
        """Статус добавлен вместе с отменой записи вместо удаления (A-2)."""
        for lang in texts.LANGUAGES:
            value = texts.get_text("status_cancelled", lang)
            assert value != "Text not found"
            assert "🚫" in value
