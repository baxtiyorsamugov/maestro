"""
Коллизии префиксов callback_data (docs/AUDIT.md, C-3).

Фильтры построены на F.data.startswith(). Если один префикс является началом
другого, то хендлер, зарегистрированный раньше, перехватывает чужие нажатия.
Ошибка не падает и не ловится линтером: кнопка просто открывает не тот экран
или не делает ничего.

Порядок проверки складывается из двух уровней: порядок роутеров в
handlers/__init__.py, а внутри роутера — порядок определения функций в файле.
Поэтому разбираем исходники, а не объекты фильтров: у aiogram нет публичного
способа спросить у MagicFilter, какую строку он матчит.

Известные пары, где порядок важен и сейчас верный:
  * set_day_off_ раньше set_day_   — иначе выходной не поставить;
  * search_district раньше search_ — иначе не открыть выбор района.
Тест зафиксирует их: переставите местами — он покраснеет.
"""
import ast
from pathlib import Path

import handlers

HANDLERS_DIR = Path(__file__).resolve().parent.parent / "handlers"


def _module_by_router() -> dict[str, Path]:
    """Файл каждого роутера по его имени."""
    mapping = {}
    for path in HANDLERS_DIR.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        marker = 'Router(name="'
        if marker in source:
            mapping[source.split(marker)[1].split('"')[0]] = path
    return mapping


def _filters_in_file(path: Path) -> list[tuple[str, str, bool]]:
    """
    Фильтры callback-хендлеров в порядке определения.

    Возвращает (строка фильтра, имя функции, это префикс или точное совпадение).
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in tree.body:
        if not isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
            continue
        for decorator in node.decorator_list:
            source = ast.unparse(decorator)
            if "callback_query" not in source:
                continue

            for chunk in source.split("startswith(")[1:]:
                for literal in chunk.split(")")[0].replace("(", "").split(","):
                    literal = literal.strip().strip("\"'")
                    if literal:
                        found.append((literal, node.name, True))

            if "==" in source and "startswith" not in source:
                literal = source.split("==")[1].split(")")[0].strip().strip("\"'")
                found.append((literal, node.name, False))
    return found


def ordered_filters() -> list[tuple[str, str, bool, str]]:
    """Все фильтры в том порядке, в каком их проверяет aiogram."""
    modules = _module_by_router()
    ordered = []
    for router in handlers.ROUTERS:
        path = modules.get(router.name)
        if not path:
            continue
        for literal, function, is_prefix in _filters_in_file(path):
            ordered.append((literal, function, is_prefix, router.name))
    return ordered


def shadowing_pairs() -> list[str]:
    """Пары, где первый фильтр перехватывает нажатия, предназначенные второму."""
    filters = ordered_filters()
    problems = []
    for i, (earlier, earlier_fn, earlier_is_prefix, earlier_router) in enumerate(filters):
        for later, later_fn, later_is_prefix, later_router in filters[i + 1:]:
            shadows = (
                (earlier_is_prefix and later.startswith(earlier))
                or (not earlier_is_prefix and not later_is_prefix and earlier == later)
            )
            if shadows:
                problems.append(
                    f"'{earlier}' ({earlier_router}.{earlier_fn}) перехватывает "
                    f"'{later}' ({later_router}.{later_fn})"
                )
    return problems


class TestNoShadowing:
    def test_no_callback_prefix_is_shadowed(self):
        problems = shadowing_pairs()
        assert problems == [], (
            "префикс перехватывается другим хендлером — нажатие уйдёт не туда:\n  "
            + "\n  ".join(problems)
        )

    def test_filters_are_actually_collected(self):
        """Пустой список означал бы, что проверка ничего не проверяет."""
        assert len(ordered_filters()) > 40


class TestKnownOrderDependencies:
    """
    Пары, где порядок критичен. Более длинный префикс обязан идти раньше,
    иначе короткий заберёт его нажатия себе.
    """

    def _position(self, literal: str) -> int:
        for index, (value, _fn, _is_prefix, _router) in enumerate(ordered_filters()):
            if value == literal:
                return index
        raise AssertionError(f"фильтр {literal!r} не найден — его переименовали?")

    def test_day_off_before_day(self):
        assert self._position("set_day_off_") < self._position("set_day_")

    def test_search_district_before_search(self):
        assert self._position("search_district") < self._position("search_")

    def test_stylist_card_before_services(self):
        """
        Карточка мастера ловит stylist_, услуги — book_ и maestro_.
        Порядок роутеров закреплён в handlers/__init__.py.
        """
        assert self._position("stylist_") < self._position("book_")
