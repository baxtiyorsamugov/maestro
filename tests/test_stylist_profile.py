"""
Тесты карточки мастера (docs/ROADMAP.md, Фаза 2 и Фаза 4).

До этого в карточке были только имя, рейтинг и адрес салона. Все мастера
выглядели одинаково, и выбирать клиенту было не по чему: человек жал
«Записаться» у первого попавшегося или уходил.

Отдельная история — возврат к карточке. Он собирал её второй, независимой
копией кода, и копия успела разойтись с оригиналом по четырём пунктам:
не было кнопки отзывов, поля барбершопа уходили в HTML без экранирования,
текст сидел в legacy-escape'ах, а описание и фото туда бы не доехали вовсе.
Тест ниже закрепляет, что оба пути дают одно и то же.
"""
import database as db
from services.stylist_profile import ABOUT_MAX_LEN, normalize_about


class TestNormalizeAbout:
    def test_trailing_spaces_go_away(self):
        assert normalize_about("   Стригу 12 лет   ") == "Стригу 12 лет"

    def test_line_breaks_survive(self):
        """Мастер мог разбить текст на строки — склеивать их значит портить."""
        result = normalize_about("Первая строка." + chr(10) + "Вторая строка.")

        assert chr(10) in result

    def test_indentation_inside_is_trimmed(self):
        assert normalize_about("Строка." + chr(10) + "    Вторая.") == "Строка." + chr(10) + "Вторая."

    def test_empty_becomes_none(self):
        """«Не заполнено» и «заполнено пустотой» должны выглядеть одинаково."""
        assert normalize_about("") is None
        assert normalize_about("   ") is None
        assert normalize_about(None) is None

    def test_long_text_is_trimmed_to_column_width(self):
        assert len(normalize_about("я" * 5000)) == ABOUT_MAX_LEN


class TestProfileFieldsAreOptional:
    async def test_stylist_without_profile_still_works(self, fixture_data):
        """Мастера, которые ничего не заполняли, не должны сломаться."""
        stylist = fixture_data["stylist"]

        assert stylist.about is None
        assert stylist.photo_file_id is None

    async def test_fields_save_and_read_back(self, fixture_data):
        session = fixture_data["session"]
        stylist = fixture_data["stylist"]
        stylist.about = "Стригу 12 лет"
        stylist.photo_file_id = "FILE_ID"
        await session.commit()

        fresh = await session.get(db.Stylist, stylist.id)

        assert fresh.about == "Стригу 12 лет"
        assert fresh.photo_file_id == "FILE_ID"


class TestCardText:
    """Текст карточки, которую мастер видит про себя."""

    def _stylist(self, about=None, photo=None):
        stylist = db.Stylist(name="Мастер")
        stylist.about = about
        stylist.photo_file_id = photo
        return stylist

    def test_empty_card_explains_what_is_missing(self):
        from handlers.stylist.profile_card import build_card_text

        text = build_card_text(self._stylist(), "ru")

        assert "не заполнено" in text
        assert "Фото: нет" in text

    def test_filled_card_shows_the_text(self):
        from handlers.stylist.profile_card import build_card_text

        text = build_card_text(self._stylist(about="Стригу 12 лет", photo="ID"), "ru")

        assert "Стригу 12 лет" in text

    def test_about_is_escaped(self):
        """
        Описание пишет мастер, а сообщение уходит с parse_mode=HTML.
        Неэкранированный текст сломает отправку целиком.
        """
        from handlers.stylist.profile_card import build_card_text

        text = build_card_text(self._stylist(about="<b>жирный</b>"), "ru")

        assert "<b>жирный</b>" not in text
        assert "&lt;b&gt;" in text

    def test_uzbek_card_has_no_russian(self):
        from handlers.stylist.profile_card import build_card_text

        text = build_card_text(self._stylist(about="Matn", photo="ID"), "uz")

        for word in ("Фото", "карточка", "заполнено"):
            assert word not in text, f"русское слово в узбекском тексте: {word}"


class TestClientCard:
    async def test_about_reaches_the_client_card(self, fixture_data):
        from handlers.client.stylist_card import load_stylist_card

        session = fixture_data["session"]
        fixture_data["stylist"].about = "Стригу 12 лет"
        await session.commit()

        card, error = await load_stylist_card(fixture_data["stylist"].id, "ru")

        assert card is not None, error
        assert "Стригу 12 лет" in card["caption"]

    async def test_photo_reaches_the_client_card(self, fixture_data):
        from handlers.client.stylist_card import load_stylist_card

        session = fixture_data["session"]
        fixture_data["stylist"].photo_file_id = "PORTRAIT_ID"
        await session.commit()

        card, _ = await load_stylist_card(fixture_data["stylist"].id, "ru")

        assert card["portrait"] == "PORTRAIT_ID"

    async def test_card_without_profile_has_no_empty_lines(self, fixture_data):
        """
        Незаполненное описание не должно оставлять в карточке дыру:
        пустая строка посреди текста выглядит как оборванное сообщение.
        """
        from handlers.client.stylist_card import load_stylist_card

        card, _ = await load_stylist_card(fixture_data["stylist"].id, "ru")

        assert chr(10) * 3 not in card["caption"]

    async def test_barbershop_fields_are_escaped(self, fixture_data):
        """
        Название салона заводит администратор через админку. В старой,
        второй сборке карточки оно уходило в HTML как есть — сообщение
        с «<» в названии Telegram отклонял целиком.
        """
        from handlers.client.stylist_card import load_stylist_card

        session = fixture_data["session"]
        shop = await session.get(db.Barbershop, fixture_data["stylist"].barbershop_id)
        shop.name = "Салон <Люкс>"
        await session.commit()

        card, _ = await load_stylist_card(fixture_data["stylist"].id, "ru")

        assert "<Люкс>" not in card["caption"]
        assert "&lt;Люкс&gt;" in card["caption"]


class TestOnlyOneCardBuilder:
    def test_back_handler_does_not_rebuild_the_card(self):
        """
        Прямая проверка исходника: возврат к карточке обязан идти через
        load_stylist_card. Вторая сборка уже однажды разошлась с первой.
        """
        import inspect

        from handlers.client import stylist_card

        source = inspect.getsource(stylist_card.back_to_stylist_card)

        assert "load_stylist_card" in source
        assert "send_card_body" in source
        assert "InlineKeyboardMarkup" not in source, "карточка собирается заново"
