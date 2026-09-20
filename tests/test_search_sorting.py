"""
Тесты подбора мастера (docs/ROADMAP.md, Фаза 4).

Список мастеров в салоне показывал только имена. Чтобы понять, кто дороже,
у кого рейтинг выше и кто освободится раньше, надо было открывать карточки
по одной и возвращаться назад. Так обычно не делают: жмут первого в списке
или уходят.

Два правила, которые здесь закрепляются.

1. Мастер, к которому нельзя записаться (нет услуг, нет свободного времени),
   всегда уходит вниз — в любом режиме сортировки. Показывать его первым
   значит обманывать: человек нажмёт и упрётся в тупик.
2. Ближайшее свободное время считается в памяти по пакетно загруженным
   данным. Если кто-то переделает это на запрос в цикле, один экран со
   списком превратится в сотни запросов.
"""
from datetime import datetime, timedelta

import database as db
import timeutils
from presenters import build_stylist_button_label
from services.search import (
    DEFAULT_SORT,
    LOOKAHEAD_DAYS,
    SORT_MODES,
    SORT_PRICE,
    SORT_RATING,
    SORT_SOONEST,
    StylistCard,
    find_nearest_slot,
    load_stylist_cards,
    sort_cards,
)


def _card(name, price=None, rating=0.0, reviews=0, nearest=None):
    stylist = db.Stylist(name=name)
    stylist.avg_rating = rating
    stylist.reviews_count = reviews
    return StylistCard(
        stylist=stylist, min_price=price, rating=rating, reviews=reviews, nearest=nearest
    )


class TestSorting:
    def test_by_rating_puts_the_best_first(self):
        cards = [_card("Слабый", rating=3.0), _card("Сильный", rating=4.9)]

        assert [c.name for c in sort_cards(cards, SORT_RATING)] == ["Сильный", "Слабый"]

    def test_equal_rating_is_broken_by_review_count(self):
        """
        Мастер с одной пятёркой не должен обходить мастера с сорока:
        одна оценка — это не репутация.
        """
        cards = [_card("Одна оценка", rating=5.0, reviews=1),
                 _card("Сорок оценок", rating=5.0, reviews=40)]

        assert sort_cards(cards, SORT_RATING)[0].name == "Сорок оценок"

    def test_by_price_puts_the_cheapest_first(self):
        cards = [_card("Дорогой", price=200000), _card("Дешёвый", price=50000)]

        assert [c.name for c in sort_cards(cards, SORT_PRICE)] == ["Дешёвый", "Дорогой"]

    def test_by_soonest_puts_the_earliest_first(self):
        now = timeutils.now()
        cards = [
            _card("Через неделю", price=1, nearest=now + timedelta(days=7)),
            _card("Завтра", price=1, nearest=now + timedelta(days=1)),
        ]

        assert [c.name for c in sort_cards(cards, SORT_SOONEST)] == ["Завтра", "Через неделю"]

    def test_default_mode_is_rating(self):
        assert DEFAULT_SORT == SORT_RATING


class TestDeadEndsGoLast:
    """Мастер, к которому нельзя записаться, не должен стоять первым."""

    def test_stylist_without_services_is_last_by_price(self):
        cards = [_card("Без услуг"), _card("С услугами", price=100000)]

        assert sort_cards(cards, SORT_PRICE)[-1].name == "Без услуг"

    def test_stylist_without_slots_is_last_by_soonest(self):
        now = timeutils.now()
        cards = [
            _card("Занят весь месяц", price=1, nearest=None),
            _card("Свободен", price=1, nearest=now + timedelta(days=3)),
        ]

        assert sort_cards(cards, SORT_SOONEST)[-1].name == "Занят весь месяц"

    def test_high_rating_does_not_rescue_a_dead_end(self):
        """
        Отличный мастер без свободного времени всё равно уходит вниз
        в режиме «кто раньше»: человек выбрал именно этот признак.
        """
        now = timeutils.now()
        cards = [
            _card("Звезда без окон", price=1, rating=5.0, nearest=None),
            _card("Обычный, но свободен", price=1, rating=3.0,
                  nearest=now + timedelta(days=1)),
        ]

        assert sort_cards(cards, SORT_SOONEST)[0].name == "Обычный, но свободен"

    def test_sorting_is_stable_for_identical_cards(self):
        """Одинаковые карточки упорядочиваются по имени, а не как попало."""
        cards = [_card("Борис", price=1, rating=4.0), _card("Алексей", price=1, rating=4.0)]

        assert [c.name for c in sort_cards(cards, SORT_PRICE)] == ["Алексей", "Борис"]


class TestNearestSlot:
    def _weekly(self, stylist_id, start="10:00", end="18:00"):
        return {
            day: db.Schedule(
                stylist_id=stylist_id, day_of_week=day, start_time=start, end_time=end
            )
            for day in range(1, 8)
        }

    def test_finds_a_slot_on_a_working_day(self):
        today = timeutils.today()
        found = find_nearest_slot(1, 60, 0, self._weekly(1), {}, {}, today)

        assert found is not None
        assert found >= timeutils.now()

    def test_returns_none_when_there_is_no_schedule(self):
        today = timeutils.today()

        assert find_nearest_slot(1, 60, 0, {}, {}, {}, today) is None

    def test_day_off_is_skipped(self):
        """Особая дата-выходной не должна давать ложное «свободно сегодня»."""
        today = timeutils.today()
        special = {today: db.SpecialSchedule(
            stylist_id=1, work_date=today, is_day_off=True
        )}

        found = find_nearest_slot(1, 60, 0, self._weekly(1), special, {}, today)

        assert found is None or found.date() != today

    def test_existing_bookings_push_the_slot_later(self):
        """Занятое время не должно предлагаться как ближайшее."""
        target = timeutils.today() + timedelta(days=3)
        weekly = self._weekly(1, "10:00", "12:00")
        booked = timeutils.parse_slot(f"{target:%Y-%m-%d} 10:00")
        bookings = {target: [db.Booking(
            stylist_id=1, starts_at=booked,
            ends_at=booked + timedelta(minutes=60), status=db.BOOKING_APPROVED,
        )]}

        found = find_nearest_slot(1, 60, 0, weekly, {}, bookings, target, days=1)

        assert found is not None
        assert found.strftime("%H:%M") == "11:00"

    def test_fully_booked_window_gives_none(self):
        target = timeutils.today() + timedelta(days=3)
        weekly = self._weekly(1, "10:00", "11:00")
        booked = timeutils.parse_slot(f"{target:%Y-%m-%d} 10:00")
        bookings = {target: [db.Booking(
            stylist_id=1, starts_at=booked,
            ends_at=booked + timedelta(minutes=60), status=db.BOOKING_APPROVED,
        )]}

        assert find_nearest_slot(1, 60, 0, weekly, {}, bookings, target, days=1) is None

    def test_buffer_is_respected(self):
        """
        Буфер мастера должен учитываться и здесь: иначе список обещает
        время, которое при попытке записаться окажется занятым.
        """
        target = timeutils.today() + timedelta(days=3)
        weekly = self._weekly(1, "10:00", "13:00")
        booked = timeutils.parse_slot(f"{target:%Y-%m-%d} 10:00")
        bookings = {target: [db.Booking(
            stylist_id=1, starts_at=booked,
            ends_at=booked + timedelta(minutes=60), status=db.BOOKING_APPROVED,
        )]}

        without = find_nearest_slot(1, 60, 0, weekly, {}, bookings, target, days=1)
        with_buffer = find_nearest_slot(1, 60, 30, weekly, {}, bookings, target, days=1)

        assert without.strftime("%H:%M") == "11:00"
        assert with_buffer is None or with_buffer > without

    def test_lookahead_is_bounded(self):
        """
        Горизонт конечен: «ближайшее через три недели» — не аргумент
        при выборе, а лишние дни расчёта на каждый показ списка.
        """
        assert LOOKAHEAD_DAYS <= 31


class TestBatchLoading:
    async def test_cards_are_built_for_every_stylist(self, fixture_data):
        session = fixture_data["session"]

        cards = await load_stylist_cards(session, [fixture_data["stylist"]])

        assert len(cards) == 1
        assert cards[0].id == fixture_data["stylist"].id

    async def test_min_price_comes_from_services(self, fixture_data):
        session = fixture_data["session"]
        session.add(db.Service(
            catalog_service_id=fixture_data["service"].catalog_service_id,
            price=50000, duration_min=30, stylist_id=fixture_data["stylist"].id,
        ))
        await session.commit()

        cards = await load_stylist_cards(session, [fixture_data["stylist"]])

        assert cards[0].min_price == 50000, "должна быть самая дешёвая услуга"

    async def test_stylist_without_services_has_no_price_and_no_slot(self, fixture_data):
        session = fixture_data["session"]
        from sqlalchemy import delete

        await session.execute(delete(db.Booking))
        await session.execute(delete(db.Service).where(
            db.Service.stylist_id == fixture_data["stylist"].id
        ))
        await session.commit()

        cards = await load_stylist_cards(session, [fixture_data["stylist"]])

        assert cards[0].min_price is None
        assert cards[0].nearest is None

    async def test_empty_list_does_not_query(self, fixture_data):
        assert await load_stylist_cards(fixture_data["session"], []) == []

    async def test_nearest_slot_reaches_the_card(self, fixture_data):
        """Связка целиком: расписание из базы должно доехать до карточки."""
        session = fixture_data["session"]
        for day in range(1, 8):
            session.add(db.Schedule(
                stylist_id=fixture_data["stylist"].id, day_of_week=day,
                start_time="10:00", end_time="18:00",
            ))
        await session.commit()

        cards = await load_stylist_cards(session, [fixture_data["stylist"]])

        assert cards[0].nearest is not None
        assert isinstance(cards[0].nearest, datetime)


class TestButtonLabel:
    def test_shows_all_three_facts(self):
        card = _card("Алишер", price=80000, rating=4.9, reviews=12,
                     nearest=timeutils.now() + timedelta(days=1))

        label = build_stylist_button_label(card, "ru")

        assert "Алишер" in label
        assert "4.9" in label
        assert "80 000" in label
        assert "завтра" in label

    def test_says_when_there_are_no_ratings(self):
        card = _card("Новичок", price=50000, nearest=timeutils.now() + timedelta(days=1))

        assert "без оценок" in build_stylist_button_label(card, "ru")

    def test_stops_early_without_services(self):
        """Без услуг говорить про «ближайшее время» бессмысленно."""
        label = build_stylist_button_label(_card("Без услуг"), "ru")

        assert "услуг пока нет" in label

    def test_says_when_there_are_no_slots(self):
        card = _card("Занят", price=50000, rating=4.0, nearest=None)

        assert "нет окон" in build_stylist_button_label(card, "ru")

    def test_uzbek_label_has_no_russian(self):
        card = _card("Alisher", price=80000, rating=4.9, reviews=12,
                     nearest=timeutils.now() + timedelta(days=1))

        label = build_stylist_button_label(card, "uz")

        for word in ("от", "завтра", "без оценок", "услуг"):
            assert word not in label, f"русское слово в узбекской подписи: {word}"


class TestSortModes:
    def test_every_mode_is_translated(self):
        import texts

        for mode in SORT_MODES:
            for lang in ("ru", "uz"):
                value = texts.get_text(f"sort_{mode}", lang)
                assert value != f"sort_{mode}", f"sort_{mode}/{lang} не переведён"

    def test_default_is_among_the_modes(self):
        assert DEFAULT_SORT in SORT_MODES
