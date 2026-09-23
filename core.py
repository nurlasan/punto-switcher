# -*- coding: utf-8 -*-
"""Общая логика переключателя: буфер набранного, конвертация, орфография.

Всё, что зависит от системы (перехват клавиш, эмуляция ввода, раскладки,
буфер обмена), вынесено в объект-бэкенд. Windows-бэкенд лежит в punto.py,
macOS - в punto_mac.py.

От бэкенда требуется:
    send_backspaces(n)      удалить n символов
    send_text(text)         напечатать текст
    switch_layout(lang)     переключить раскладку окна на "ru" или "en"
    copy_selection()        скопировать выделенное, вернуть текст
    paste(text)             вставить текст вместо выделенного
    clipboard_get/set       чтение и запись буфера обмена
    wait_modifiers_up()     дождаться отпускания модификаторов
    front_app()             идентификатор активного окна (для сброса буфера)
"""

import time

import spell
from layouts import convert, detect_direction, looks_wrong

MAX_BUFFER = 120       # сколько последних символов помним
MIN_AUTO_WORD = 3      # слова короче не рассматриваем в авто-режиме


def layout_for(text):
    """Раскладка, в которой набран текст: "ru" для кириллицы, иначе "en"."""
    return "ru" if detect_direction(text) == "ru2en" else "en"


class Switcher:
    def __init__(self, backend):
        self.be = backend
        self.buf = []              # символы, набранные в текущем окне
        self.last_app = None
        self.auto = False          # авто-раскладка
        self.auto_spell = False    # авто-орфография (только русский)
        self.injecting = False     # сейчас печатаем мы сами
        self.just_fixed = False    # чтобы не чинить одно слово дважды

    # ---- буфер набранного ----------------------------------------------
    def reset(self):
        self.buf = []
        self.just_fixed = False

    def on_char(self, ch):
        """Пользователь напечатал символ. Возвращает True, если пора проверять слово."""
        if self.injecting:
            return False
        app = self.be.front_app()
        if app != self.last_app:
            self.last_app = app
            self.reset()

        self.buf.append(ch)
        del self.buf[:-MAX_BUFFER]
        if not ch.isspace():
            return False
        check = self.auto and not self.just_fixed
        self.just_fixed = False
        return check

    def on_backspace(self):
        if self.injecting:
            return
        if self.buf:
            self.buf.pop()
        self.just_fixed = False

    # ---- работа со словом ----------------------------------------------
    def tail_word(self):
        """(последнее слово, число хвостовых пробелов)."""
        i, ws = len(self.buf), 0
        while i > 0 and self.buf[i - 1].isspace():
            i -= 1
            ws += 1
        j = i
        while j > 0 and not self.buf[j - 1].isspace():
            j -= 1
        return "".join(self.buf[j:i]), ws

    def replace_tail(self, word, ws, new_word):
        tail_ws = "".join(self.buf[len(self.buf) - ws:]) if ws else ""
        self.injecting = True
        try:
            self.be.send_backspaces(len(word) + ws)
            time.sleep(0.015)
            self.be.send_text(new_word + tail_ws)
            time.sleep(0.02)
        finally:
            self.injecting = False
        del self.buf[len(self.buf) - len(word) - ws:]
        self.buf.extend(new_word + tail_ws)
        self.be.switch_layout(layout_for(new_word))

    # ---- команды --------------------------------------------------------
    def convert_word(self):
        """Перевести последнее слово в другую раскладку (ручная команда)."""
        word, ws = self.tail_word()
        if not word:
            return
        self.be.wait_modifiers_up()
        self.replace_tail(word, ws, convert(word))
        self.just_fixed = True

    def spell_word(self):
        """Исправить опечатку в последнем слове (ручная команда)."""
        word, ws = self.tail_word()
        if not word:
            return
        fixed = spell.correct(word)
        if not fixed:
            return
        self.be.wait_modifiers_up()
        self.replace_tail(word, ws, fixed)
        self.just_fixed = True

    def auto_fix(self):
        """Автоматическая проверка последнего слова: сначала раскладка, потом опечатки."""
        word, ws = self.tail_word()
        if len(word) >= MIN_AUTO_WORD and looks_wrong(word):
            self.replace_tail(word, ws, convert(word))
            self.just_fixed = True
            return
        # орфография - только русский: в английском слишком много технических
        # терминов, которых нет в словарях (backend, cors, chown), и правка их ломает
        if self.auto_spell and spell.lang_of(word) == "ru":
            fixed = spell.correct(word, strict=True)
            if fixed:
                self.replace_tail(word, ws, fixed)
                self.just_fixed = True

    def convert_selection(self):
        """Перевести выделенный текст через буфер обмена."""
        self.be.wait_modifiers_up()
        saved = self.be.clipboard_get()
        self.injecting = True
        try:
            text = self.be.copy_selection()
            if not text.strip():
                return
            new = convert(text)
            self.be.paste(new)
            self.be.switch_layout(layout_for(new))
        finally:
            self.injecting = False
            if saved:
                time.sleep(0.05)
                self.be.clipboard_set(saved)
        self.reset()

    # ---- состояние ------------------------------------------------------
    def toggle_auto(self):
        self.auto = not self.auto
        return self.auto

    def toggle_spell(self):
        self.auto_spell = not self.auto_spell
        return self.auto_spell

    def status(self):
        parts = ["раскладка: авто" if self.auto else "раскладка: вручную"]
        if self.auto_spell:
            parts.append("орфография: авто")
        return "Punto (" + ", ".join(parts) + ")"
