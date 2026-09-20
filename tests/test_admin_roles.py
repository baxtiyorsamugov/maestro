"""
Тесты ролей в веб-панели (docs/ROADMAP.md, Фаза 7).

До этого учётная запись была одна: любой, у кого есть доступ к панели, мог
всё — правя́ть тарифы, удалять учётные записи клиентов, скрывать отзывы.
Администратору на ресепшене, которому надо разбирать заявки, приходилось
давать те же права, что и владельцу.

Права ломаются незаметно: ошибка не роняет ничего, просто однажды помощник
может больше, чем должен, и узнают об этом по последствиям. Поэтому здесь
проверяется каждая пара «роль × действие», а не только счастливый путь.

Отдельно проверяется подпись в журнале: без неё действие помощника
записалось бы на владельца, и журнал врал бы ровно там, где его читают.
"""
import pytest

import security


class FakeSettings:
    def __init__(self, manager=True):
        self.username = "owner"
        self.password = "owner-pass"
        self.secret_key = "x" * 32
        self.manager_username = "helper" if manager else None
        self.manager_password = "helper-pass" if manager else None


class FakeRequest:
    """Минимальный запрос: роль решается по сессии и пути."""

    def __init__(self, session=None, path="/admin/booking/list"):
        self.session = session if session is not None else {}
        self.url = type("Url", (), {"path": path})()


class TestAuthentication:
    def test_owner_credentials_give_owner(self):
        role = security.authenticate_admin("owner", "owner-pass", FakeSettings())

        assert role == security.ROLE_OWNER

    def test_manager_credentials_give_manager(self):
        role = security.authenticate_admin("helper", "helper-pass", FakeSettings())

        assert role == security.ROLE_MANAGER

    def test_wrong_password_gives_nothing(self):
        assert security.authenticate_admin("owner", "мимо", FakeSettings()) is None

    def test_wrong_username_gives_nothing(self):
        assert security.authenticate_admin("кто-то", "owner-pass", FakeSettings()) is None

    def test_manager_password_with_owner_login_is_refused(self):
        """Перепутанные половины двух пар не должны складываться в вход."""
        assert security.authenticate_admin("owner", "helper-pass", FakeSettings()) is None

    def test_manager_is_optional(self):
        """Вторая учётная запись необязательна: у большинства её нет."""
        settings = FakeSettings(manager=False)

        assert security.authenticate_admin("owner", "owner-pass", settings) == security.ROLE_OWNER
        assert security.authenticate_admin("helper", "helper-pass", settings) is None

    def test_hashed_password_works(self):
        """Пароль хранится хешем; открытый принимается ради совместимости."""
        settings = FakeSettings()
        settings.password = security.hash_password("owner-pass")

        assert security.authenticate_admin("owner", "owner-pass", settings) == security.ROLE_OWNER
        assert security.authenticate_admin("owner", "мимо", settings) is None

    def test_empty_credentials_are_refused(self):
        assert security.authenticate_admin("", "", FakeSettings()) is None


class TestSessionRole:
    def _admin(self, monkeypatch):
        import admin_panel

        monkeypatch.setattr(admin_panel, "ADMIN_SETTINGS", FakeSettings())
        return admin_panel

    def test_valid_session_gives_its_role(self, monkeypatch):
        admin_panel = self._admin(monkeypatch)
        request = FakeRequest({"token": "x" * 32, "role": security.ROLE_MANAGER})

        assert admin_panel.current_role(request) == security.ROLE_MANAGER

    def test_session_without_role_is_invalid(self, monkeypatch):
        """
        Такие сессии остались у тех, кто вошёл до появления ролей.
        Считать их владельцами было бы удобнее и неправильно: права
        не выдают по умолчанию. Цена — один повторный вход.
        """
        admin_panel = self._admin(monkeypatch)
        request = FakeRequest({"token": "x" * 32})

        assert admin_panel.current_role(request) is None

    def test_unknown_role_is_invalid(self):
        """Подделанная роль в cookie не должна что-либо давать."""
        import admin_panel

        request = FakeRequest({"token": admin_panel.ADMIN_SETTINGS.secret_key, "role": "superuser"})

        assert admin_panel.current_role(request) is None

    def test_wrong_token_is_invalid(self, monkeypatch):
        admin_panel = self._admin(monkeypatch)
        request = FakeRequest({"token": "y" * 32, "role": security.ROLE_OWNER})

        assert admin_panel.current_role(request) is None

    def test_empty_session_is_invalid(self, monkeypatch):
        admin_panel = self._admin(monkeypatch)

        assert admin_panel.current_role(FakeRequest({})) is None


class TestWriteDetection:
    """
    Чтение от записи отличается по пути: sqladmin зовёт is_accessible()
    одинаково на всех эндпоинтах. Ошибка здесь открыла бы помощнику запись
    везде, и заметить это по поведению панели было бы нельзя.
    """

    import admin_panel

    @pytest.mark.parametrize("path", [
        "/admin/user/create",
        "/admin/user/edit/7",
        "/admin/user/delete",
    ])
    def test_write_paths_are_detected(self, path):
        import admin_panel

        assert admin_panel.is_write_request(FakeRequest(path=path)) is True

    @pytest.mark.parametrize("path", [
        "/admin/user/list",
        "/admin/user/details/7",
        "/admin",
    ])
    def test_read_paths_are_not(self, path):
        import admin_panel

        assert admin_panel.is_write_request(FakeRequest(path=path)) is False


class TestViewPermissions:
    def _request(self, role, path):
        import admin_panel

        return FakeRequest(
            {"token": admin_panel.ADMIN_SETTINGS.secret_key, "role": role}, path=path
        )

    def test_owner_can_write_everywhere(self):
        import admin_panel

        for view in (admin_panel.UserAdmin(), admin_panel.BookingAdmin(),
                     admin_panel.StylistAdmin()):
            request = self._request(security.ROLE_OWNER, "/admin/x/edit/1")
            assert view.is_accessible(request) is True, type(view).__name__

    def test_manager_can_read_everything(self):
        """«Только просмотр и записи» — просмотр не урезается."""
        import admin_panel

        for view in (admin_panel.UserAdmin(), admin_panel.StylistAdmin(),
                     admin_panel.BarbershopAdmin()):
            request = self._request(security.ROLE_MANAGER, "/admin/x/list")
            assert view.is_accessible(request) is True, type(view).__name__

    def test_manager_can_edit_bookings(self):
        """Разбор заявок — и есть работа помощника."""
        import admin_panel

        request = self._request(security.ROLE_MANAGER, "/admin/booking/edit/1")

        assert admin_panel.BookingAdmin().is_accessible(request) is True

    @pytest.mark.parametrize("view_name", [
        "UserAdmin", "StylistAdmin", "BarbershopAdmin",
        "ServiceAdmin", "CatalogServiceAdmin", "ScheduleAdmin", "PortfolioAdmin",
    ])
    def test_manager_cannot_write_anything_else(self, view_name):
        """
        Тарифы, учётные записи клиентов, справочники — не его зона.
        Перечислены поимённо: новое представление по умолчанию попадёт
        под запрет, но в этом списке его не будет, и это заметят.
        """
        import admin_panel

        view = getattr(admin_panel, view_name)()
        request = self._request(security.ROLE_MANAGER, "/admin/x/edit/1")

        assert view.is_accessible(request) is False, view_name

    def test_manager_cannot_delete(self):
        import admin_panel

        request = self._request(security.ROLE_MANAGER, "/admin/user/delete")

        assert admin_panel.UserAdmin().is_accessible(request) is False

    def test_nobody_without_session_gets_in(self):
        import admin_panel

        request = FakeRequest({}, path="/admin/user/list")

        assert admin_panel.UserAdmin().is_accessible(request) is False

    def test_default_is_owner_only(self):
        """
        Право на запись выдаётся явно. Представление, забывшее объявить
        writable_by, достаётся владельцу, а не всем.
        """
        import admin_panel

        assert admin_panel.RoleAwareView.writable_by == (security.ROLE_OWNER,)


class TestReviewModerationPage:
    def test_manager_does_not_see_the_button(self):
        """
        Кнопка, которая ответит отказом, хуже отсутствующей: помощник
        решит, что панель сломана, а не что у него нет прав.
        """
        from admin_panel import _render_reviews

        row = {
            "id": 1, "author": "Клиент", "stylist": "Мастер", "rating": 5,
            "when": "2098-01-01 12:00", "text": "Хорошо", "hidden": False,
        }
        html = _render_reviews([row], can_moderate=False)

        assert "<form" not in html
        assert "<button" not in html
        assert "владелец" in html, "надо объяснить, почему кнопки нет"

    def test_owner_sees_the_button(self):
        from admin_panel import _render_reviews

        row = {
            "id": 1, "author": "Клиент", "stylist": "Мастер", "rating": 5,
            "when": "2098-01-01 12:00", "text": "Хорошо", "hidden": False,
        }
        html = _render_reviews([row], can_moderate=True)

        assert "/reviews/1/toggle" in html


class TestAuditSignature:
    def test_moderation_is_signed_by_the_logged_in_user(self):
        """
        Прямая проверка исходника: подпись берётся из сессии, а не из
        настроек. Иначе действие помощника записалось бы на владельца —
        и журнал врал бы ровно там, где его читают.
        """
        import inspect

        import admin_panel

        source = inspect.getsource(admin_panel.toggle_review_visibility)

        assert "current_username(request)" in source
        assert "ADMIN_SETTINGS.username" not in source

    def test_manager_is_refused_moderation(self):
        import inspect

        import admin_panel

        source = inspect.getsource(admin_panel.toggle_review_visibility)

        assert "ROLE_OWNER" in source, "скрытие отзыва должно быть только у владельца"
