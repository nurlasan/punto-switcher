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

    print("Короткие слова")
    check("предлог сам по себе", core.short_wrong("yf"), True)
    check("одна буква без соседей", core.short_wrong("d"), False)
    check("одна буква после русского", core.short_wrong("d", True), True)
    check("английский предлог", core.short_wrong("шт"), True)
    check("vs не трогаем", core.short_wrong("vs"), False)
    check("английское in не трогаем", core.short_wrong("in"), False)

    for name, text, want in (
            ("предлог на лету", "yf ", "на "),
            ("местоимение на лету", "jy ", "он "),
            ("предлог перед словом", "d ujhjl ", "в город "),
            ("цепочка коротких", "z e nt,z ", "я у тебя "),
            ("буква после русского", "иду d ", "иду в "),
            ("английские короткие", "шы ше ", "is it "),
            ("английский текст цел", "plan b vs it in ", "plan b vs it in ")):
        be = FakeBackend()
        be.text = ""
        sw = core.Switcher(be)
        sw.auto = sw.auto_spell = True
        for ch in text:
            be.text += ch
            if sw.on_char(ch):
                sw.auto_fix()
        check(name, be.text, want)

    print("Двойной пробел")
    for name, text, auto, want in (
            ("слово без авто-режима", "ghbdtn  ", False, "привет "),
            ("буква", "d  ", False, "в "),
            ("английское слово", "руддщ  ", False, "hello "),
            ("откат авто-перевода", "ghbdtn  ", True, "ghbdtn "),
            ("один пробел - ничего", "ghbdtn ", False, "ghbdtn "),
            ("отступ не трогаем", "  ", False, "  ")):
        be = FakeBackend()
        sw = core.Switcher(be)
        sw.auto = sw.auto_spell = auto
        for ch in text:
            be.text += ch
            if sw.on_char(ch):
                sw.auto_fix()
        check(name, be.text, want)

    be = FakeBackend()
    sw = core.Switcher(be)
    for ch in "ghbdtn ":
        be.text += ch
        sw.on_char(ch)
    sw.last_space -= 1                 # второй пробел через секунду
    be.text += " "
    if sw.on_char(" "):
        sw.auto_fix()
    check("медленный двойной пробел", be.text, "ghbdtn  ")

    print("Двойной Ctrl / Alt / Shift")
    sw = core.Switcher(FakeBackend())
    sw.trigger = "ctrl"
    check("одно нажатие", sw.on_modifier("ctrl"), False)
    check("второе нажатие", sw.on_modifier("ctrl"), True)
    check("третье - снова с нуля", sw.on_modifier("ctrl"), False)
    sw.on_char("a")
    check("буква между нажатиями", sw.on_modifier("ctrl"), False)
    sw.on_modifier(None)               # Ctrl+Shift и т.п.
    check("сочетание между нажатиями", sw.on_modifier("ctrl"), False)
    sw.reset()
    check("не тот модификатор", (sw.on_modifier("alt"), sw.on_modifier("alt")), (False, False))
    sw.on_modifier("ctrl")
    sw.last_tap = ("ctrl", sw.last_tap[1] - 1)
    check("медленно", sw.on_modifier("ctrl"), False)

    be = FakeBackend()
    sw = core.Switcher(be)
    sw.trigger = "ctrl"
    for ch in "ghbdtn  ":
        be.text += ch
        if sw.on_char(ch):
            sw.auto_fix()
    check("пробел не срабатывает при Ctrl", be.text, "ghbdtn  ")
    sw.on_modifier("ctrl")
    if sw.on_modifier("ctrl"):
        sw.convert_word()
    check("двойной Ctrl переводит", be.text, "привет  ")

    print("Одно нажатие")
    saved, core.save_settings = core.save_settings, lambda **kw: None   # не трогать settings.json
    try:
        sw = core.Switcher(FakeBackend())
        sw.trigger = "space"
        sw.set_taps(1)
        check("пробел при 1 нажатии -> Ctrl", (sw.taps, sw.trigger), (1, "ctrl"))
        sw.set_trigger("space")
        check("одиночный пробел не выбрать", sw.trigger, "ctrl")
        check("нажали - ещё рано", sw.on_modifier("ctrl"), False)
        check("отпустили - переводим", sw.on_modifier_up("ctrl"), True)
        sw.on_modifier("ctrl")
        sw.on_char("c")                    # Ctrl+C
        check("Ctrl+C не срабатывает", sw.on_modifier_up("ctrl"), False)
        sw.on_modifier("ctrl")
        sw.on_modifier(None)               # Ctrl+Shift
        check("Ctrl+Shift не срабатывает", sw.on_modifier_up("ctrl"), False)
        sw.on_modifier("ctrl")
        sw.tap_down = ("ctrl", sw.tap_down[1] - 1)
        check("долго держали", sw.on_modifier_up("ctrl"), False)
        check("чужой модификатор", (sw.on_modifier("alt"), sw.on_modifier_up("alt")), (False, False))
        sw.set_taps(2)
        sw.on_modifier("ctrl")
        check("при 2 нажатиях отпускание не считается", sw.on_modifier_up("ctrl"), False)
        sw.apply_settings({"taps": 1, "trigger": "space"}, "ctrl")
        check("мусор в настройках", (sw.taps, sw.trigger), (1, "ctrl"))
    finally:
        core.save_settings = saved

    print("Английская авто-орфография")
    for bad, good in (("seperate", "separate"), ("lenght", "length"),
                      ("managment", "management"), ("occured", "occurred"),
                      ("dont", "don't"), ("accross", "across")):
        check(bad, spell.suggest(bad, strict=True), good)
    for word in ("stdio", "endian", "clientid", "sstream", "Marvell", "minmax"):
        check(f"{word} не трогаем", spell.suggest(word, strict=True), None)

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
