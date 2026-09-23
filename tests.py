# -*- coding: utf-8 -*-
"""Тесты общей логики - работают на любой системе, без перехвата клавиш.

    py tests.py          (Windows)
    python3 tests.py     (macOS)
"""

import sys

import core
import spell
from layouts import convert, looks_wrong


class FakeBackend:
    """Бэкенд-заглушка: запоминает, что программа напечатала бы."""

    def __init__(self):
        self.text = ""
        self.layout = None
        self.clipboard = ""
        self.selection = ""

    def send_backspaces(self, n):
        self.text = self.text[:-n] if n else self.text

    def send_text(self, text):
        self.text += text

    def switch_layout(self, lang):
        self.layout = lang

    def clipboard_get(self):
        return self.clipboard

    def clipboard_set(self, text):
        self.clipboard = text

    def copy_selection(self):
        return self.selection

    def paste(self, text):
        self.selection = text

    def wait_modifiers_up(self):
        pass

    def front_app(self):
        return 1


def typed(sw, text):
    """Имитирует набор текста пользователем."""
    for ch in text:
        if sw.on_char(ch):
            sw.auto_fix()


FAILS = []


def check(name, got, want):
    ok = got == want
    if not ok:
        FAILS.append(f"{name}: получили {got!r}, ждали {want!r}")
    print(f"  {'OK  ' if ok else 'ПЛОХО'} {name}: {got!r}")


def main():
    print("Словари и модель")
    check("конвертация", convert("ghbdtn"), "привет")
    check("обратно", convert("привет"), "ghbdtn")
    check("не та раскладка", looks_wrong("ghbdtn"), True)
    check("нормальное слово", looks_wrong("привет"), False)
    check("термин не трогаем", looks_wrong("mqtt"), False)

    print("Орфография")
    check("опечатка авто", spell.suggest("делаится", strict=True), "делается")
    check("опечатка вручную", spell.suggest("recieve"), "receive")
    check("жаргон не трогаем", spell.suggest("батч", strict=True), None)
    check("английский в авто", spell.suggest("backend", strict=True), None)
    check("автозамена", spell.suggest("тоесть", strict=True), "то есть")

    print("Набор текста с авто-режимом")
    be = FakeBackend()
    sw = core.Switcher(be)
    sw.auto = sw.auto_spell = True
    typed(sw, "ghjdthrf ")
    check("раскладка на лету", be.text, "проверка ")
    check("раскладка переключена", be.layout, "ru")

    be = FakeBackend()
    sw = core.Switcher(be)
    sw.auto = sw.auto_spell = True
    typed(sw, "нармальному ")
    check("опечатка на лету", be.text, "нормальному ")

    be = FakeBackend()
    sw = core.Switcher(be)
    sw.auto = sw.auto_spell = True
    typed(sw, "батч бэкенд привет ")
    check("своё не тронуто", be.text, "")

    print("Ручные команды")
    be = FakeBackend()
    sw = core.Switcher(be)
    typed(sw, "ghbdtn")
    sw.convert_word()
    check("Pause на слове", be.text, "привет")

    be = FakeBackend()
    sw = core.Switcher(be)
    typed(sw, "привте")
    sw.spell_word()
    check("ручная орфография", be.text, "привет")

    be = FakeBackend()
    be.selection = "ghbdtn"
    sw = core.Switcher(be)
    sw.convert_selection()
    check("выделенный текст", be.selection, "привет")

    print()
    if FAILS:
        print(f"ОШИБОК: {len(FAILS)}")
        for line in FAILS:
            print("  -", line)
        return 1
    print("всё в порядке")
    return 0


if __name__ == "__main__":
    sys.exit(main())
