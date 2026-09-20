"""
Проверка кодировки исходников. Запускается в CI.

Два класса багов, которые не видно глазами и которые проект уже ловил:

1. Повреждённая кириллица — 35 строк интерфейса однажды схлопнулись в "?????"
   после записи файла в однобайтовой кодировке (docs/AUDIT.md, A-1).
   Текст тогда был утрачен безвозвратно.

2. Суррогатные пары — эмодзи, записанное как "\\ud83d\\udeab" вместо символа.
   Такая строка компилируется и выглядит правдоподобно, но в UTF-8 не кодируется
   и уходит в Telegram мусором.

Проверяем не текст файла, а разобранные строковые литералы: иначе проверка
спотыкается о собственную документацию, где эти примеры упомянуты.

Локально: python scripts/check_encoding.py
"""
import ast
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Три подряд знака вопроса в пользовательском тексте — почти наверняка
# схлопнувшаяся кириллица, а не осмысленная строка.
# Собирается из частей намеренно: иначе проверка находит саму себя.
MOJIBAKE_MARKER = "?" * 3

# Второй пласт той же порчи: символ превратился не в «?», а в перенос строки.
# «доступны\nрайонов» вместо «доступных районов» — строка выглядит обычной,
# и проверка на «???» её не видит.
#
# Кириллическая буква вплотную перед переносом: нормальный перенос ставят
# после знака препинания или законченной фразы, а не посреди слова.
EATEN_LETTER = re.compile(r"[а-яёА-ЯЁ]\n")

# Вариационный селектор без символа перед ним: было эмодзи, осталась приправа.
EATEN_EMOJI = re.compile(r"(?:^|\n|\s)️")


def tracked_python_files() -> list[Path]:
    """
    Файлы под контролем версий плюс новые, ещё не добавленные в индекс.

    --others --exclude-standard добавляет неотслеживаемые файлы, не попавшие
    в .gitignore. Без этого проверка молча пропускала только что созданный
    файл: локально всё зелено, а CI краснеет после коммита — ровно этим
    и закончилась задача про офлайн-записи.

    Команда фиксированная, пользовательского ввода в ней нет.
    """
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "*.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    # Файл может быть и в индексе, и в выводе --others — убираем повторы,
    # сохраняя порядок, чтобы вывод проверки был стабильным.
    seen = dict.fromkeys(line for line in result.stdout.splitlines() if line.strip())
    return [ROOT / line for line in seen]


def string_literals(tree: ast.AST):
    """Все строковые литералы, кроме докстрингов: в них примеры багов законны."""
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            doc = ast.get_docstring(node, clean=False)
            if doc is not None:
                docstrings.add(doc)

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value in docstrings:
                continue
            yield node.lineno, node.value


def check_file(path: Path) -> list[str]:
    problems = []
    source = path.read_text(encoding="utf-8")

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as e:
        return [f"{path.relative_to(ROOT)}: не разбирается — {e}"]

    for lineno, value in string_literals(tree):
        rel = path.relative_to(ROOT)

        if MOJIBAKE_MARKER in value:
            problems.append(f"{rel}:{lineno}: повреждённая кириллица — {value[:50]!r}")

        surrogates = [hex(ord(ch)) for ch in value if 0xD800 <= ord(ch) <= 0xDFFF]
        if surrogates:
            problems.append(f"{rel}:{lineno}: суррогатные пары {surrogates} — {value[:40]!r}")

        if EATEN_LETTER.search(value):
            problems.append(
                f"{rel}:{lineno}: перенос строки вплотную после кириллицы — "
                f"похоже, вместо символа, {value[:50]!r}"
            )

        if EATEN_EMOJI.search(value):
            problems.append(
                f"{rel}:{lineno}: вариационный селектор без эмодзи перед ним — "
                f"символ съеден, {value[:40]!r}"
            )

    return problems


def main() -> int:
    files = tracked_python_files()
    print(f"Проверка кодировки: {len(files)} файлов (в индексе и новые)")

    problems = []
    for path in files:
        if not path.exists():
            continue
        problems.extend(check_file(path))

    if problems:
        print("\nНАЙДЕНЫ ПРОБЛЕМЫ:")
        for problem in problems:
            print("  ", problem)
        print("\nТекст пишется как есть, в UTF-8. Подробности — docs/CONVENTIONS.md.")
        return 1

    print("Кодировка в порядке")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
