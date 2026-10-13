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

import json
import time

import spell
from layouts import APP_NAME, user_file
from layouts import CYRILLIC, LATIN, convert, detect_direction, looks_wrong, short_wrong

MAX_BUFFER = 120       # сколько последних символов помним
MIN_AUTO_WORD = 3      # слова короче проверяем по спискам служебных слов
MAX_LOOKBACK = 3       # сколько коротких слов перед словом переводить заодно
DOUBLE_SPACE = 0.4     # два пробела быстрее этого (сек) - перевести слово
DOUBLE_TAP = 0.35      # то же для двойного Ctrl / Alt / Shift
TAP_HOLD = 0.5         # одиночное нажатие: отпустить не позже чем через столько

# чем переводить последнее слово: клавиша и число нажатий (1 или 2);
# пробел - только двойной, иначе переводилось бы каждое слово
TRIGGERS = ("ctrl", "alt", "shift", "space", "off")
TAPS = (1, 2)
SETTINGS = user_file("settings.json")


def load_settings():
    try:
        with open(SETTINGS, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(**values):
    data = load_settings()
    data.update(values)
    try:
        with open(SETTINGS, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    except OSError:
        pass


def layout_for(text):
    """Раскладка, в которой набран текст: "ru" для кириллицы, иначе "en"."""
    return "ru" if detect_direction(text) == "ru2en" else "en"


class Switcher:
    def __init__(self, backend):
        self.be = backend
        self.buf = []              # символы, набранные в текущем окне
        self.last_app = None
        self.auto = False          # авто-раскладка
        self.auto_spell = False    # авто-орфография
        self.injecting = False     # сейчас печатаем мы сами
        self.just_fixed = False    # чтобы не чинить одно слово дважды
        self.trigger = "space"     # см. TRIGGERS
        self.taps = 2              # сколько раз нажимать, см. TAPS
        self.tap_down = None       # (модификатор, время) - одиночное нажатие в процессе
        self.last_space = 0.0      # когда нажат предыдущий пробел
        self.pending_double = False
        self.last_tap = (None, 0.0)   # (модификатор, время) прошлого нажатия

    # ---- буфер набранного ----------------------------------------------
    def reset(self):
        self.buf = []
        self.just_fixed = False
        self.cancel_taps()

    def cancel_taps(self):
        """Между нажатиями модификатора было что-то ещё - начинаем счёт заново."""
        self.last_tap = (None, 0.0)
        self.tap_down = None

    def on_char(self, ch):
        """Пользователь напечатал символ. Возвращает True, если пора проверять слово."""
        if self.injecting:
            return False
        app = self.be.front_app()
        if app != self.last_app:
            self.last_app = app
            self.reset()

        self.cancel_taps()
        self.buf.append(ch)
        del self.buf[:-MAX_BUFFER]
        if not ch.isspace():
            return False
        if ch == " ":
            now = time.monotonic()
            if (self.trigger == "space" and now - self.last_space < DOUBLE_SPACE
                    and len(self.buf) >= 3 and self.buf[-2] == " "
                    and not self.buf[-3].isspace()):
                self.pending_double = True
            self.last_space = now
        check = (self.auto and not self.just_fixed) or self.pending_double
        self.just_fixed = False
        return check

    def on_backspace(self):
        if self.injecting:
            return
        self.cancel_taps()
        if self.buf:
            self.buf.pop()
        self.just_fixed = False

    def on_modifier(self, name):
        """Нажат модификатор ("ctrl", "alt", "shift") сам по себе; None - в сочетании.

        Возвращает True, если это второе нажатие подряд и выбранный способ
        перевода - он; тогда бэкенд вызывает convert_word в главном потоке.
        Для одного нажатия решение принимает on_modifier_up.
        """
        if self.injecting or name is None or name != self.trigger:
            self.cancel_taps()
            return False
        now = time.monotonic()
        if self.taps == 1:
            self.tap_down = (name, now)
            return False
        prev, when = self.last_tap
        if prev == name and now - when <= DOUBLE_TAP:
            self.last_tap = (None, 0.0)
            return True
        self.last_tap = (name, now)
        return False

    def on_modifier_up(self, name):
        """Модификатор отпущен. True - это одиночное нажатие, пора переводить.

        Считается, только если между нажатием и отпусканием не было других
        клавиш (Ctrl+C не срабатывает) и клавишу не держали дольше TAP_HOLD.
        """
        down, self.tap_down = self.tap_down, None
        if self.injecting or self.taps != 1 or not down or down[0] != name:
            return False
        return time.monotonic() - down[1] <= TAP_HOLD

    def set_trigger(self, trigger):
        if trigger not in TRIGGERS or (trigger == "space" and self.taps == 1):
            return
        self.trigger = trigger
        self.cancel_taps()
        save_settings(trigger=trigger)

    def set_taps(self, taps):
        if taps not in TAPS:
            return
        self.taps = taps
        if taps == 1 and self.trigger == "space":
            self.trigger = "ctrl"
        self.cancel_taps()
        save_settings(taps=taps, trigger=self.trigger)

    def apply_settings(self, settings, default_trigger):
        """Способ перевода из settings.json (с проверкой на мусор)."""
        self.taps = settings.get("taps", 2) if settings.get("taps") in TAPS else 2
        trigger = settings.get("trigger", default_trigger)
        self.trigger = trigger if trigger in TRIGGERS else default_trigger
        if self.taps == 1 and self.trigger == "space":
            self.trigger = "ctrl"

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
        if self.pending_double:
            self.pending_double = False
            self.double_space_convert()
            return
        if not self.auto:
            return
        word, ws = self.tail_word()
        start = len(self.buf) - ws - len(word)
        if len(word) >= MIN_AUTO_WORD:
            if looks_wrong(word):
                self.convert_span(self.short_before(start, word), ws)
                return
        elif short_wrong(word, self.prev_is_other(start, word)):
            self.convert_span(start, ws)
            return
        if self.auto_spell:
            fixed = spell.correct(word, strict=True)
            if fixed:
                self.replace_tail(word, ws, fixed)

    def double_space_convert(self):
        """Слово и два пробела -> слово в другой раскладке и один пробел.

        Работает и на словах, которые авто-режим не тронул, и на тех, что он
        перевёл зря: повторный перевод возвращает как было.
        """
        word, ws = self.tail_word()
        if ws != 2 or not word or convert(word) == word:
            return
        self.replace_tail(word + " ", 1, convert(word))

    def prev_is_other(self, start, word):
        """Предыдущее слово набрано не тем алфавитом, что word."""
        prev = "".join(self.buf[:start]).rstrip(" ").rsplit(None, 1)
        if not prev:
            return False
        alphabet = LATIN if detect_direction(word) == "ru2en" else CYRILLIC
        return any(ch in alphabet for ch in prev[-1])

    def short_before(self, start, word):
        """Начало участка с короткими словами перед word, набранными в той же
        неверной раскладке («yf ckjdf» -> «на слова», а не «yf слова»)."""
        for _ in range(MAX_LOOKBACK):
            i = start
            while i > 0 and self.buf[i - 1] == " ":
                i -= 1
            j = i
            while j > 0 and not self.buf[j - 1].isspace():
                j -= 1
            token = "".join(self.buf[j:i])
            if i == start or not token or detect_direction(token) != detect_direction(word):
                break
            if not short_wrong(token, context=True):
                break
            start = j
        return start

    def convert_span(self, start, ws):
        """Перевести в другую раскладку буфер от start до хвостовых пробелов."""
        text = "".join(self.buf[start:len(self.buf) - ws])
        self.replace_tail(text, ws, convert(text))

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
        save_settings(auto=self.auto)
        return self.auto

    def toggle_spell(self):
        self.auto_spell = not self.auto_spell
        save_settings(spell=self.auto_spell)
        return self.auto_spell

    def status(self):
        parts = ["раскладка: авто" if self.auto else "раскладка: вручную"]
        if self.auto_spell:
            parts.append("орфография: авто")
        return APP_NAME + " (" + ", ".join(parts) + ")"
