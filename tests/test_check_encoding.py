"""
Правила scripts/check_encoding.py.

Сама проверка — последний рубеж против порчи текста (docs/AUDIT.md, A-1),
и до этого файла её никто не проверял. Примеры порчи собираются из частей
через chr(92): иначе проверка нашла бы их в исходнике этого же теста.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import check_encoding

BS = chr(92)


def escape(text: str) -> str:
    """«Ра» → «<обратный слеш>u0420<обратный слеш>u0430»."""
    return "".join(f"{BS}u{ord(ch):04x}" for ch in text)


class TestVisibleEscapes:
    def test_cyrillic_escape_in_comment_is_found(self):
        """Ровно тот случай: комментарий в guards.py лёг escape'ами."""
        source = f"x = 1\n# {escape('Раньше')}\n"
        found = check_encoding.visible_escapes(source)
        assert found and found[0][0] == 2

    def test_escape_in_string_is_found(self):
        source = f'text = "{escape("Привет")}"\n'
        assert check_encoding.visible_escapes(source)

    def test_escaped_dash_is_found(self):
        source = f"# a {BS}u2014 b\n"
        assert check_encoding.visible_escapes(source)

    def test_double_backslash_is_documentation(self):
        """Описание escape'а в тексте («\\\\u0447 вместо ч») — не нарушение."""
        source = f'"""{BS}{BS}u0447 вместо «ч»"""\n'
        assert check_encoding.visible_escapes(source) == []

    def test_invisible_characters_may_stay_escaped(self):
        """Неразрывный пробел и селектор эмодзи иначе в коде не видно."""
        source = f'NBSP = "{BS}u00a0"\nVS = "{BS}ufe0f"\n'
        assert check_encoding.visible_escapes(source) == []

    def test_plain_text_is_fine(self):
        assert check_encoding.visible_escapes("# Раньше — так.\nx = 'Привет'\n") == []


class TestCheckFile:
    def test_file_with_escapes_is_reported(self, tmp_path, monkeypatch):
        monkeypatch.setattr(check_encoding, "ROOT", tmp_path)
        path = tmp_path / "bad.py"
        path.write_text(f"# {escape('Раньше')}\nx = 1\n", encoding="utf-8")

        problems = check_encoding.check_file(path)

        assert any("escape" in p for p in problems), problems

    def test_mixed_line_endings_are_reported(self, tmp_path, monkeypatch):
        monkeypatch.setattr(check_encoding, "ROOT", tmp_path)
        path = tmp_path / "mixed.py"
        path.write_bytes(b"a = 1\r\nb = 2\n")

        assert check_encoding.check_file(path)

    def test_clean_file_passes(self, tmp_path, monkeypatch):
        monkeypatch.setattr(check_encoding, "ROOT", tmp_path)
        path = tmp_path / "ok.py"
        path.write_text("# Раньше — так.\nx = 'Привет'\n", encoding="utf-8")

        assert check_encoding.check_file(path) == []
