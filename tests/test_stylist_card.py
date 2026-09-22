"""
Услуги с ценами на карточке мастера (docs/ROADMAP.md, Фаза 4).

Раньше цены были только на экране записи: чтобы узнать, по карману ли
мастер, приходилось начинать запись.
"""
from types import SimpleNamespace

import database as db
import presenters
from test_scenarios import _open_workday, person, world  # noqa: F401 — фикстура world

CYRILLIC = __import__("re").compile(r"[а-яА-ЯёЁ]")


def _service(name, price, minutes=60):
    return SimpleNamespace(
        catalog_service=SimpleNamespace(name=name), price=price, duration_min=minutes,
    )


class TestServicesBlock:
    def test_cheapest_first_with_price_and_duration(self):
        block = presenters.build_card_services_block(
            [_service("Борода", 80_000, 30), _service("Стрижка", 50_000, 45)], "ru",
        )
        lines = block.splitlines()
        assert "Стрижка" in lines[1] and "50 000" in lines[1] and "45 мин" in lines[1]
        assert "Борода" in lines[2]

    def test_long_list_is_cut_with_a_count(self):
        services = [_service(f"S{i}", 10_000 * i) for i in range(1, 9)]
        block = presenters.build_card_services_block(services, "ru")
        assert block.count("•") == presenters.CARD_SERVICES_SHOWN
        assert "ещё 3" in block

    def test_no_services_no_empty_header(self):
        assert presenters.build_card_services_block([], "ru") == ""

    def test_names_are_escaped(self):
        block = presenters.build_card_services_block([_service("Fade <VIP>", 1)], "ru")
        assert "&lt;VIP&gt;" in block

    def test_uzbek_block_has_no_russian(self):
        block = presenters.build_card_services_block(
            [_service("Soch olish", 50_000)] + [_service("x", 1)] * 6, "uz",
        )
        assert not CYRILLIC.search(block), block


class TestCardThroughDispatcher:
    async def test_card_shows_service_price(self, world, fixture_data):  # noqa: F811
        await _open_workday(fixture_data)
        client = person(world, fixture_data["client_user"].telegram_id, "Клиент")

        replies = await client.press(f"stylist_{fixture_data['stylist'].id}")

        assert replies.answered_callback
        assert "100 000" in replies.last_text, replies.last_text

    async def test_long_caption_with_portrait_is_split(self, world, fixture_data):  # noqa: F811
        """
        Подпись к фото ограничена 1024 символами. Длинное описание вместе
        с услугами её превышает — Telegram отклонил бы карточку целиком.
        """
        await _open_workday(fixture_data)
        stylist = fixture_data["stylist"]
        stylist.photo_file_id = "portrait-file-id"
        # Мимо normalize_about, напрямую: проверяем отправку, а не лимит описания.
        # 500 символов описания + 5 услуг в 1024 ещё укладываются, а длинный
        # адрес салона (свободный текст из админки) — уже нет.
        stylist.about = "Опыт " * 180
        session = fixture_data["session"]
        catalog = db.CatalogService(name="Очень длинное название услуги для проверки")
        session.add(catalog)
        await session.flush()
        for i in range(10):
            session.add(db.Service(
                catalog_service_id=catalog.id, price=10_000 + i, duration_min=30,
                stylist_id=stylist.id,
            ))
        await session.commit()

        client = person(world, fixture_data["client_user"].telegram_id, "Клиент")
        replies = await client.press(f"stylist_{stylist.id}")

        photos = [c for c in replies.calls if type(c).__name__ == "SendPhoto"]
        assert photos, "портрет не отправлен"
        assert not photos[0].caption, "длинный текст остался в подписи — сценарий не проверяет разбиение"
        assert all(len(p.caption or "") <= 1024 for p in photos), "подпись длиннее предела"
        text_messages = [c for c in replies.calls if type(c).__name__ == "SendMessage"]
        assert text_messages and text_messages[-1].reply_markup, "текст карточки без кнопок"

    async def test_short_caption_stays_on_the_photo(self, world, fixture_data):  # noqa: F811
        await _open_workday(fixture_data)
        fixture_data["stylist"].photo_file_id = "portrait-file-id"
        await fixture_data["session"].commit()

        client = person(world, fixture_data["client_user"].telegram_id, "Клиент")
        replies = await client.press(f"stylist_{fixture_data['stylist'].id}")

        photos = [c for c in replies.calls if type(c).__name__ == "SendPhoto"]
        assert len(photos) == 1 and photos[0].caption and photos[0].reply_markup
