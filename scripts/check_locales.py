"""
Проверка текстов интерфейса. Запускается в CI.

1. Наборы ключей ru и uz обязаны совпадать. Если перевода нет, get_text вернёт
   русский текст — узбекоязычный пользователь молча получит испорченный интерфейс,
   и заметит это только он.

2. Ни в одной строке не должно быть суррогатных пар. Эмодзи, записанное как
   \\ud83d\\udeab вместо 🚫, выглядит в исходнике правдоподобно, но в Telegram
   уходит мусором — глазами такое не ловится.

Локально: python scripts/check_locales.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import texts


def check_completeness(name: str, source: dict) -> int:
    all_keys = set(source)
    problems = 0

    for lang in texts.LANGUAGES:
        missing = sorted(
            key for key in all_keys
            if not str(source[key].get(lang, "")).strip()
        )
        if missing:
            problems += len(missing)
            print(f"  [{name}] нет перевода на '{lang}': {', '.join(missing)}")

    if not problems:
        print(f"  [{name}] {len(all_keys)} ключей, оба языка на месте")
    return problems


def check_surrogates(name: str, source: dict) -> int:
    problems = 0
    for key, translations in source.items():
        for lang, value in translations.items():
            broken = [hex(ord(ch)) for ch in str(value) if 0xD800 <= ord(ch) <= 0xDFFF]
            if broken:
                problems += 1
                print(f"  [{name}] суррогаты в {key}/{lang}: {broken}")
    return problems


def main() -> int:
    print("Проверка текстов интерфейса")

    problems = 0
    for name, source in (("TEXTS", texts.TEXTS), ("BUTTONS", texts.BUTTONS)):
        problems += check_completeness(name, source)
        problems += check_surrogates(name, source)

    if problems:
        print(f"\nПРОБЛЕМ: {problems}")
        print("Каждый пользовательский текст добавляется сразу на ru и uz,")
        print("эмодзи пишется символом, а не escape-последовательностью.")
        return 1

    print("\nВсё в порядке")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
