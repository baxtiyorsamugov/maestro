"""
Тесты разбора параметра диплинка (docs/AUDIT.md, B-4).

Рассылка «пора обновить образ» шлёт ссылку https://t.me/<bot>?start=stylist_<id>.
Раньше параметр игнорировался: клиент нажимал ссылку из письма и попадал
в общее меню, не понимая, зачем нажимал. Вся возвратная кампания теряла смысл.
"""
import pytest

from handlers.client import registration, stylist_card


class TestParseStartPayload:
    @pytest.mark.parametrize(
        ("payload", "expected"),
        [
            ("12", 12),
            ("stylist_12", 12),
            ("1", 1),
            ("  7  ", 7),
            ("stylist_999", 999),
        ],
    )
    def test_valid_payloads(self, payload, expected):
        assert registration.parse_start_payload(payload) == expected

    @pytest.mark.parametrize(
        "payload",
        [
            None,
            "",
            "   ",
            "мусор",
            "stylist_",
            "stylist_abc",
            "-5",
            "0",
            "12.5",
            "12; DROP TABLE bookings",
            "stylist_12_extra",
        ],
    )
    def test_invalid_payloads_are_ignored(self, payload):
        """Мусор не должен ломать /start — человек просто попадёт в меню."""
        assert registration.parse_start_payload(payload) is None

    def test_zero_is_not_a_valid_id(self):
        assert registration.parse_start_payload("0") is None

    def test_huge_number_does_not_raise(self):
        assert registration.parse_start_payload("9" * 50) == int("9" * 50)


class TestStylistCard:
    async def test_card_loads_for_active_stylist(self, fixture_data):
        card, error = await stylist_card.load_stylist_card(fixture_data["stylist"].id, "ru")
        assert error is None
        assert card is not None
        assert "Мастер" in card["caption"]
        assert card["keyboard"] is not None

    async def test_missing_stylist_returns_error(self, fixture_data):
        card, error = await stylist_card.load_stylist_card(999999, "ru")
        assert card is None
        assert "не найден" in error

    async def test_expired_subscription_blocks_card(self, fixture_data):
        import datetime

        session = fixture_data["session"]
        fixture_data["stylist_user"].subscription_until = datetime.date(2000, 1, 1)
        await session.commit()

        card, error = await stylist_card.load_stylist_card(fixture_data["stylist"].id, "ru")
        assert card is None
        assert "недоступен" in error

    async def test_card_shows_reviews_count(self, fixture_data):
        session = fixture_data["session"]
        fixture_data["stylist"].avg_rating = 4.0
        fixture_data["stylist"].reviews_count = 7
        await session.commit()

        card, _ = await stylist_card.load_stylist_card(fixture_data["stylist"].id, "ru")
        assert "(7)" in card["caption"]

    async def test_card_escapes_stylist_name(self, fixture_data):
        session = fixture_data["session"]
        fixture_data["stylist"].name = "<b>взлом</b>"
        await session.commit()

        card, _ = await stylist_card.load_stylist_card(fixture_data["stylist"].id, "ru")
        assert "&lt;b&gt;взлом&lt;/b&gt;" in card["caption"]

    async def test_card_available_in_uzbek(self, fixture_data):
        card, error = await stylist_card.load_stylist_card(fixture_data["stylist"].id, "uz")
        assert error is None
        assert "Maestro" in card["caption"]
