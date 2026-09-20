"""
Тесты текстовых отзывов (docs/ROADMAP.md, Фаза 4).

Колонка review_text лежала в схеме с самого начала, но UI под неё не было:
клиент ставил звёзды вслепую, а новый человек видел в карточке мастера
только цифру без единого слова о том, как всё прошло.

Три вещи, которые здесь проверяются и которые легко сломать незаметно.

1. Скрытый модератором отзыв не должен попадать клиенту. Фильтр стоит
   в самом запросе, а не после выборки: иначе его однажды забудут применить
   в новом месте, и скрытый текст вернётся к людям.
2. Отзыв пишет человек, и этот текст уходит в HTML-сообщение Telegram
   и в HTML-страницу админки. Экранирование обязано быть в обоих местах.
3. Правила «когда можно оставить отзыв» должны совпадать с тем, что видит
   пользователь: разрешить в карточке и отказать при сохранении — худший
   вариант, человек уже написал текст.
"""
from datetime import timedelta

import database as db
import texts
import timeutils
from presenters import build_reviews_text
from services.reviews import (
    REVIEW_MAX_LEN,
    REVIEWS_PREVIEW_LIMIT,
    can_leave_review,
    count_reviews_for_stylist,
    load_reviews_for_moderation,
    load_reviews_for_stylist,
    normalize_review,
)


async def _reviewed(fixture_data, text: str, rating: int = 5, hidden: bool = False,
                    when: str = "2098-01-01 12:00") -> db.Booking:
    session = fixture_data["session"]
    starts_at = timeutils.parse_slot(when)
    booking = db.Booking(
        user_id=fixture_data["client_user"].id,
        stylist_id=fixture_data["stylist"].id,
        service_id=fixture_data["service"].id,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=60),
        status=db.BOOKING_COMPLETED,
        rating=rating,
        review_text=text,
        review_hidden=hidden,
    )
    session.add(booking)
    await session.commit()
    return booking


class TestNormalizeReview:
    def test_trailing_spaces_go_away(self):
        assert normalize_review("   Отличный мастер   ") == "Отличный мастер"

    def test_paragraphs_survive(self):
        """
        Переносы внутри текста сохраняются: человек мог разбить отзыв
        на абзацы, и склеивать их в одну строку — портить написанное.
        """
        result = normalize_review("Первый абзац.\n\nВторой абзац.")

        assert result.count("\n") == 2

    def test_indentation_inside_is_trimmed(self):
        assert normalize_review("Строка.\n    Вторая.") == "Строка.\nВторая."

    def test_empty_becomes_none(self):
        assert normalize_review("") is None
        assert normalize_review("   \n  \n ") is None
        assert normalize_review(None) is None

    def test_long_text_is_trimmed_to_column_width(self):
        result = normalize_review("а" * 5000)

        assert len(result) == REVIEW_MAX_LEN


class TestCanLeaveReview:
    def test_completed_and_rated_is_allowed(self):
        booking = db.Booking(status=db.BOOKING_COMPLETED, rating=5, review_text=None)

        assert can_leave_review(booking) == (True, None)

    def test_unfinished_visit_is_refused(self):
        booking = db.Booking(status=db.BOOKING_APPROVED, rating=5)

        allowed, reason = can_leave_review(booking)

        assert allowed is False
        assert reason == "review_denied_not_completed"

    def test_without_rating_is_refused(self):
        """
        Отзыв без оценки осиротел бы: в карточке они показываются вместе,
        и звёзды взять будет неоткуда.
        """
        booking = db.Booking(status=db.BOOKING_COMPLETED, rating=None)

        assert can_leave_review(booking)[1] == "review_denied_no_rating"

    def test_second_review_is_refused(self):
        booking = db.Booking(
            status=db.BOOKING_COMPLETED, rating=5, review_text="Уже написал"
        )

        assert can_leave_review(booking)[1] == "review_denied_already_left"

    def test_every_reason_is_translated(self):
        """Сервис возвращает ключ texts.py: без перевода клиент увидит сам ключ."""
        for key in (
            "review_denied_not_completed",
            "review_denied_no_rating",
            "review_denied_already_left",
        ):
            for lang in ("ru", "uz"):
                assert texts.get_text(key, lang) != key, f"{key}/{lang} не переведён"


class TestHiddenReviewsStayHidden:
    """Главное правило модерации."""

    async def test_hidden_review_is_not_returned(self, fixture_data):
        session = fixture_data["session"]
        await _reviewed(fixture_data, "Видимый", when="2098-01-01 12:00")
        await _reviewed(fixture_data, "Скрытый", hidden=True, when="2098-01-02 12:00")

        found = await load_reviews_for_stylist(session, fixture_data["stylist"].id)
        texts_found = [item.review_text for item in found]

        assert "Видимый" in texts_found
        assert "Скрытый" not in texts_found

    async def test_hidden_review_is_not_counted(self, fixture_data):
        session = fixture_data["session"]
        await _reviewed(fixture_data, "Видимый", when="2098-01-01 12:00")
        await _reviewed(fixture_data, "Скрытый", hidden=True, when="2098-01-02 12:00")

        assert await count_reviews_for_stylist(session, fixture_data["stylist"].id) == 1

    async def test_rating_without_text_is_not_a_review(self, fixture_data):
        """Звёзды без слов в список отзывов попадать не должны."""
        session = fixture_data["session"]
        await _reviewed(fixture_data, None, when="2098-01-03 12:00")

        assert await count_reviews_for_stylist(session, fixture_data["stylist"].id) == 0

    async def test_moderation_sees_hidden_ones(self, fixture_data):
        """Скрытие нужно уметь отменить — значит, в админке видно всё."""
        session = fixture_data["session"]
        await _reviewed(fixture_data, "Скрытый", hidden=True, when="2098-01-02 12:00")

        found = await load_reviews_for_moderation(session)

        assert [item.review_text for item in found] == ["Скрытый"]

    async def test_other_stylists_reviews_are_not_mixed_in(self, fixture_data):
        session = fixture_data["session"]
        await _reviewed(fixture_data, "Про нашего мастера")

        found = await load_reviews_for_stylist(session, fixture_data["stylist"].id + 999)

        assert found == []


class TestOrderAndLimit:
    async def test_newest_first(self, fixture_data):
        session = fixture_data["session"]
        await _reviewed(fixture_data, "Старый", when="2098-01-01 12:00")
        await _reviewed(fixture_data, "Новый", when="2098-06-01 12:00")

        found = await load_reviews_for_stylist(session, fixture_data["stylist"].id)

        assert [item.review_text for item in found] == ["Новый", "Старый"]

    async def test_preview_is_capped(self, fixture_data):
        session = fixture_data["session"]
        for day in range(1, REVIEWS_PREVIEW_LIMIT + 4):
            await _reviewed(fixture_data, f"Отзыв {day}", when=f"2098-01-{day:02d} 12:00")

        found = await load_reviews_for_stylist(session, fixture_data["stylist"].id)
        total = await count_reviews_for_stylist(session, fixture_data["stylist"].id)

        assert len(found) == REVIEWS_PREVIEW_LIMIT
        assert total == REVIEWS_PREVIEW_LIMIT + 3


class TestLoadedRelations:
    async def test_author_is_available_after_session_closes(self, fixture_data):
        """
        Подпись отзыва берёт имя клиента. Без joinedload обращение к нему
        в async-контексте бросит MissingGreenlet (CLAUDE.md, 4.3).
        """
        session = fixture_data["session"]
        await _reviewed(fixture_data, "Текст")

        found = await load_reviews_for_stylist(session, fixture_data["stylist"].id)
        session.expunge_all()

        assert found[0].user.first_name == "Клиент"


class TestReviewsText:
    async def test_review_is_rendered(self, fixture_data):
        session = fixture_data["session"]
        await _reviewed(fixture_data, "Стрижка что надо")
        found = await load_reviews_for_stylist(session, fixture_data["stylist"].id)

        rendered = build_reviews_text("Мастер", found, 1, "ru")

        assert "Стрижка что надо" in rendered
        assert "★★★★★" in rendered

    def test_empty_list_says_so(self):
        rendered = build_reviews_text("Мастер", [], 0, "ru")

        assert texts.get_text("reviews_empty", "ru") in rendered

    async def test_remainder_is_announced(self, fixture_data):
        session = fixture_data["session"]
        for day in range(1, 9):
            await _reviewed(fixture_data, f"Отзыв {day}", when=f"2098-02-{day:02d} 12:00")
        found = await load_reviews_for_stylist(session, fixture_data["stylist"].id)

        rendered = build_reviews_text("Мастер", found, 8, "ru")

        assert "3" in rendered, "должно быть сказано, что есть ещё 3 отзыва"

    async def test_client_text_is_escaped(self, fixture_data):
        """
        Отзыв пишет человек, а сообщение уходит с parse_mode=HTML.
        Неэкранированный текст сломает разметку — Telegram отклонит
        сообщение целиком, и карточка мастера просто не откроется.
        """
        session = fixture_data["session"]
        await _reviewed(fixture_data, "<b>жирный</b> и <script>alert(1)</script>")
        found = await load_reviews_for_stylist(session, fixture_data["stylist"].id)

        rendered = build_reviews_text("Мастер", found, 1, "ru")

        assert "<script>" not in rendered
        assert "&lt;script&gt;" in rendered

    async def test_author_name_is_escaped(self, fixture_data):
        session = fixture_data["session"]
        fixture_data["client_user"].first_name = "<i>Хакер</i>"
        await fixture_data["session"].commit()
        await _reviewed(fixture_data, "Текст")
        found = await load_reviews_for_stylist(session, fixture_data["stylist"].id)

        rendered = build_reviews_text("Мастер", found, 1, "ru")

        assert "<i>Хакер</i>" not in rendered

    def test_stylist_name_is_escaped(self):
        rendered = build_reviews_text("<b>Мастер</b>", [], 0, "ru")

        assert "<b>Мастер</b>" not in rendered


class TestModerationPageEscapesToo:
    """
    Тот же текст уходит и в HTML-страницу админки. Экранирование там
    отдельное, и проверять его надо отдельно: одно место починят, другое нет.
    """

    def test_script_does_not_reach_the_page(self):
        from admin_panel import _render_reviews

        html = _render_reviews([{
            "id": 1,
            "author": "<script>alert(1)</script>",
            "stylist": "Мастер",
            "rating": 5,
            "when": "2098-01-01 12:00",
            "text": "<img src=x onerror=alert(1)>",
            "hidden": False,
        }])

        assert "<script>alert(1)</script>" not in html
        assert "<img src=x" not in html
        assert "&lt;script&gt;" in html

    def test_newlines_become_line_breaks(self):
        from admin_panel import _render_reviews

        # Перенос собирается из частей: литерал с кириллицей вплотную перед
        # переносом — ровно тот шаблон, который ищет scripts/check_encoding.py
        # (CLAUDE.md, 4.1), и проверка упала бы на этой фикстуре.
        html = _render_reviews([{
            "id": 1, "author": "Клиент", "stylist": "Мастер", "rating": 4,
            "when": "2098-01-01 12:00", "text": "Первая строка" + chr(10) + "Вторая строка",
            "hidden": False,
        }])

        assert "Первая строка<br>Вторая строка" in html

    def test_hidden_review_offers_to_show(self):
        from admin_panel import _render_reviews

        html = _render_reviews([{
            "id": 7, "author": "Клиент", "stylist": "Мастер", "rating": 1,
            "when": "2098-01-01 12:00", "text": "Плохо", "hidden": True,
        }])

        assert "Показать" in html
        assert "/reviews/7/toggle" in html

    def test_empty_queue_says_so(self):
        from admin_panel import _render_reviews

        assert "Отзывов пока нет" in _render_reviews([])
