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
import unicodedata
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

# Видимый не-ASCII символ, записанный escape-последовательностью: «Ра...»
# вместо «Ра...». Читать и ревьюить такое невозможно, а CLAUDE.md, 4.1 запрещает
# новые escape'ы. Правило однажды нарушилось незаметно — инструмент правки
# подхватил стиль файла, где escape'ы уже были, — поэтому теперь проверяется
# машиной. Ищем в исходном тексте, а не в литералах: в комментариях порча та же,
# а после разбора escape из литерала уже не отличить от обычного символа.
# Двойной обратный слеш — описание escape'а в документации, его не трогаем.
VISIBLE_ESCAPE = re.compile(r"(?<!\\)\\u([0-9a-fA-F]{4})")


def visible_escapes(source: str) -> list[tuple[int, str]]:
    """(номер строки, escape) для каждого escape'а видимого не-ASCII символа."""
    found = []
    for lineno, line in enumerate(source.splitlines(), start=1):
        for match in VISIBLE_ESCAPE.finditer(line):
            char = chr(int(match.group(1), 16))
            # Невидимые и управляющие символы (неразрывный пробел, селекторы)
            # escape'ом как раз и пишут — иначе их не видно в коде.
            if ord(char) >= 0x80 and unicodedata.category(char)[0] not in "CZM":
                found.append((lineno, match.group(0)))
    return found


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


def mixed_line_endings(raw: bytes) -> tuple[int, int] | None:
    """
    Смешанные окончания строк внутри одного файла: (CRLF, голых LF) или None.

    Это отпечаток дописывания файла через `cat >>` или `echo >>` из bash:
    файл в рабочем дереве хранится с CRLF, а дописанное ложится с LF.
    Именно так однажды сгорели 35 строк интерфейса (docs/AUDIT.md, A-1),
    и CLAUDE.md, 4.1 запрещает этот способ — но запрет на бумаге однажды
    нарушается. Кириллица при этом может и уцелеть; смешанные окончания
    остаются всегда, поэтому ловим именно их.

    Файл целиком в LF — не проблема: git сам приводит окончания при коммите.
    Проблема только в смеси внутри одного файла.
    """
    crlf = raw.count(b"\r\n")
    lf_only = raw.count(b"\n") - crlf
    if crlf and lf_only:
        return crlf, lf_only
    return None


def check_file(path: Path) -> list[str]:
    problems = []
    raw = path.read_bytes()

    mixed = mixed_line_endings(raw)
    if mixed:
        problems.append(
            f"{path.relative_to(ROOT)}: смешанные окончания строк "
            f"(CRLF {mixed[0]}, голых LF {mixed[1]}) — похоже на дописывание "
            f"через bash; правьте файл инструментом Edit/Write"
        )

    # Как раньше делал read_text: универсальные переводы строк. Иначе правило
    # EATEN_LETTER увидело бы \r\n там, где раньше видело \n, и поменяло бы
    # поведение без всякой на то причины.
    source = raw.decode("utf-8").replace("\r\n", "\n")

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as e:
        return [f"{path.relative_to(ROOT)}: не разбирается — {e}"]

    escapes = visible_escapes(source)
    if escapes:
        lineno, sample = escapes[0]
        problems.append(
            f"{path.relative_to(ROOT)}:{lineno}: текст записан escape-последовательностями "
            f"({len(escapes)} шт., например {sample}) — пишите символы как есть"
        )

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
