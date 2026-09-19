"""
Тесты сборки роутеров (docs/ROADMAP.md, Фаза 3).

Порядок подключения роутеров — это порядок проверки фильтров. Ошибка здесь
не падает и не ловится линтером: бот просто перестаёт реагировать на часть
кнопок, а выяснится это от пользователей.

Самый опасный случай — fallback: он отвечает на всё подряд, и если окажется
не последним, съест вообще все остальные хендлеры.
"""
import bot  # noqa: F401 — импорт собирает диспетчер и подключает роутеры
import handlers
import loader


class TestRouterOrder:
    def test_fallback_is_registered_last(self):
        assert handlers.ROUTERS[-1] is handlers.fallback.router, (
            "fallback отвечает на любое сообщение: не последним он перехватит всё"
        )

    def test_no_duplicate_routers(self):
        names = [r.name for r in handlers.ROUTERS]
        assert len(names) == len(set(names)), f"роутер подключён дважды: {names}"

    def test_every_router_has_handlers(self):
        empty = [
            r.name for r in handlers.ROUTERS
            if not (r.message.handlers or r.callback_query.handlers)
        ]
        assert empty == [], f"пустые роутеры: {empty}"


class TestDispatcherAssembly:
    def test_all_routers_are_included(self):
        included = {r.name for r in loader.dp.sub_routers}
        expected = {r.name for r in handlers.ROUTERS}
        assert expected <= included, f"не подключены: {expected - included}"

    def test_fallback_is_last_in_dispatcher(self):
        assert loader.dp.sub_routers[-1].name == "fallback"

    def test_handler_count_is_not_lost(self):
        """
        Хендлеры переезжали между модулями: если при следующем переносе
        часть потеряется, бот молча перестанет отвечать на эти кнопки.

        Числа ниже — не требование, а страховка. Добавили хендлер намеренно —
        обновите их в том же коммите; упало без вашего ведома — что-то потерялось.
        """
        expected_messages = 23
        expected_callbacks = 58  # 57 доменных + catch-all для устаревших кнопок

        total_messages = len(loader.dp.message.handlers) + sum(
            len(r.message.handlers) for r in loader.dp.sub_routers
        )
        total_callbacks = len(loader.dp.callback_query.handlers) + sum(
            len(r.callback_query.handlers) for r in loader.dp.sub_routers
        )

        assert total_messages == expected_messages, (
            f"message-хендлеров стало {total_messages}, ожидалось {expected_messages}"
        )
        assert total_callbacks == expected_callbacks, (
            f"callback-хендлеров стало {total_callbacks}, ожидалось {expected_callbacks}"
        )

    def test_error_handler_stays_on_dispatcher(self):
        """
        Обработчик ошибок должен быть на диспетчере, а не в роутере:
        только так он поймает исключения из всех роутеров сразу.
        """
        assert len(loader.dp.errors.handlers) == 1
