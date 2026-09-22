"""
Адрес клиента, лимит запросов и /health в веб-панели (docs/ROADMAP.md, Фаза 7).

Главное здесь — не сам лимит, а уязвимость, найденная по дороге к нему:
адрес для блокировки входа брался из X-Forwarded-For без условий. Этот
заголовок пишет клиент, и перебор пароля, меняя его на каждой попытке,
не блокировался никогда.
"""
import httpx
import pytest

import security

TRUSTED = security.parse_networks("127.0.0.1,::1,172.16.0.0/12")


class TestClientAddress:
    def test_header_from_untrusted_peer_is_ignored(self):
        """Прямое соединение: заголовок подделан самим клиентом."""
        assert security.client_address("203.0.113.7", "1.2.3.4", TRUSTED) == "203.0.113.7"

    def test_spoofing_does_not_change_the_key(self):
        """Ровно та атака: новый заголовок на каждой попытке — ключ тот же."""
        keys = {
            security.client_address("203.0.113.7", f"10.0.0.{i}", TRUSTED) for i in range(20)
        }
        assert keys == {"203.0.113.7"}

    def test_trusted_proxy_passes_the_real_address(self):
        assert security.client_address("127.0.0.1", "203.0.113.7", TRUSTED) == "203.0.113.7"

    def test_rightmost_untrusted_hop_wins(self):
        """
        Клиент прислал «1.2.3.4» сам, nginx дописал настоящий адрес в конец.
        Первый адрес — ложь клиента, верить надо правому.
        """
        header = "1.2.3.4, 203.0.113.7"
        assert security.client_address("127.0.0.1", header, TRUSTED) == "203.0.113.7"

    def test_chain_of_trusted_proxies_is_skipped(self):
        header = "203.0.113.7, 172.18.0.1"
        assert security.client_address("127.0.0.1", header, TRUSTED) == "203.0.113.7"

    def test_docker_gateway_is_trusted_by_network(self):
        assert security.client_address("172.18.0.1", "203.0.113.7", TRUSTED) == "203.0.113.7"

    def test_garbage_in_header_does_not_crash(self):
        assert security.client_address("127.0.0.1", "not-an-ip", TRUSTED) == "not-an-ip"
        assert security.client_address("127.0.0.1", " , ", TRUSTED) == "127.0.0.1"

    def test_missing_peer(self):
        assert security.client_address(None, None, TRUSTED) == "unknown"


class TestSettings:
    def test_bad_proxy_value_is_reported(self, monkeypatch):
        import config

        monkeypatch.setenv("ADMIN_TRUSTED_PROXIES", "127.0.0.1,nginx-host")
        problems = config.describe_problems(("admin",))
        assert any("ADMIN_TRUSTED_PROXIES" in p and "nginx-host" in p for p in problems), problems


class TestRateLimiter:
    def test_allows_up_to_limit_then_refuses(self):
        limiter = security.RequestRateLimiter(limit=3, window_seconds=60)
        assert [limiter.hit("a", now=t) for t in (0, 1, 2)] == [0, 0, 0]
        assert limiter.hit("a", now=3) > 0

    def test_retry_after_points_to_window_end(self):
        limiter = security.RequestRateLimiter(limit=1, window_seconds=60)
        limiter.hit("a", now=100)
        assert 55 <= limiter.hit("a", now=105) <= 56

    def test_window_slides(self):
        limiter = security.RequestRateLimiter(limit=1, window_seconds=60)
        limiter.hit("a", now=0)
        assert limiter.hit("a", now=61) == 0

    def test_keys_are_independent(self):
        limiter = security.RequestRateLimiter(limit=1, window_seconds=60)
        limiter.hit("a", now=0)
        assert limiter.hit("b", now=0) == 0

    def test_memory_is_bounded(self):
        """Поток с разных адресов не должен раздувать память без предела."""
        limiter = security.RequestRateLimiter(limit=5, window_seconds=60, max_keys=100)
        for i in range(1000):
            limiter.hit(f"k{i}", now=i * 61)
        assert len(limiter._hits) <= 101


@pytest.fixture
async def panel(monkeypatch):
    import admin_panel

    # Свежие счётчики на каждый тест: лимитеры — модульные объекты.
    monkeypatch.setattr(admin_panel, "HEALTH_LIMITER", security.RequestRateLimiter(limit=3))
    monkeypatch.setattr(admin_panel, "PANEL_LIMITER", security.RequestRateLimiter(limit=5))
    monkeypatch.setattr(admin_panel, "login_throttle", security.LoginThrottle())

    def client_from(peer):
        transport = httpx.ASGITransport(app=admin_panel.app, client=(peer, 12345))
        return httpx.AsyncClient(transport=transport, base_url="http://panel")

    yield client_from


class TestPanel:
    async def test_health_is_limited(self, panel):
        async with panel("203.0.113.7") as client:
            codes = [(await client.get("/health")).status_code for _ in range(4)]
        assert codes[:3] == [200, 200, 200]
        assert codes[3] == 429

    async def test_429_has_retry_after(self, panel):
        async with panel("203.0.113.7") as client:
            for _ in range(3):
                await client.get("/health")
            response = await client.get("/health")
        assert response.status_code == 429
        assert int(response.headers["retry-after"]) > 0

    async def test_spoofed_header_does_not_reset_the_limit(self, panel):
        async with panel("203.0.113.7") as client:
            codes = [
                (await client.get("/health", headers={"X-Forwarded-For": f"10.0.0.{i}"})).status_code
                for i in range(4)
            ]
        assert codes[3] == 429, "подмена X-Forwarded-For обошла лимит"

    async def test_login_lockout_survives_spoofing(self, panel):
        """
        Та самая атака на вход: пять неверных паролей с новым заголовком
        каждый раз. Шестая попытка — даже с верным паролем — отклоняется.
        """
        import admin_panel

        async with panel("203.0.113.7") as client:
            for i in range(5):
                await client.post(
                    "/admin/login",
                    data={"username": "x", "password": "мимо"},
                    headers={"X-Forwarded-For": f"10.0.0.{i}"},
                )
        assert admin_panel.login_throttle.is_locked("203.0.113.7") > 0

    async def test_health_hides_database_error_details(self, panel, monkeypatch):
        import admin_panel

        class Boom(Exception):
            pass

        class BrokenEngine:
            def connect(self):
                raise Boom("password authentication failed for user maestro at db:5432")

        monkeypatch.setattr(admin_panel.db, "engine", BrokenEngine())
        async with panel("127.0.0.1") as client:
            body = (await client.get("/health")).json()

        assert body["database"] == "error"
        assert "maestro" not in str(body) and "5432" not in str(body)
