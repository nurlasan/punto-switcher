# -*- coding: utf-8 -*-
"""Переключатель раскладки для macOS (RU <-> EN) - порт punto.py.

Логика общая (core.py, layouts.py, spell.py), здесь только системная часть:
перехват клавиш через CGEventTap, эмуляция ввода, переключение раскладки
через Text Input Sources и значок в строке меню.

Горячие клавиши (по умолчанию):
    двойной пробел     - перевести последнее слово в другую раскладку
                         (в меню можно выбрать двойной ⌃, ⌥ или Shift)
    ⌃⌥L                - то же самое
    ⌃⌥⇧L               - перевести выделенный текст
    ⌃⌥S                - исправить опечатку в последнем слове
    ⌃⌥A                - вкл/выкл авто-режим раскладки
    ⌃⌥P                - вкл/выкл авто-орфографию
    ⌃⌥Q                - выход

Требуется: python3 -m pip install pyobjc-framework-Cocoa pyobjc-framework-Quartz
и разрешение в Системных настройках → Конфиденциальность → Универсальный доступ.

    python3 punto_mac.py --check     # диагностика без перехвата
    python3 punto_mac.py --auto --spell
"""

import ctypes
import ctypes.util
import sys
import time

import AppKit
import objc
import Quartz
from PyObjCTools import AppHelper

import core

# ---------------------------------------------------------------- константы

KEY_BACKSPACE = 51
KEY_C, KEY_V = 8, 9
KEY_A, KEY_L, KEY_P, KEY_Q, KEY_S = 0, 37, 35, 12, 1

MASK_SHIFT = Quartz.kCGEventFlagMaskShift
MASK_CONTROL = Quartz.kCGEventFlagMaskControl
MASK_OPTION = Quartz.kCGEventFlagMaskAlternate
MASK_COMMAND = Quartz.kCGEventFlagMaskCommand
MODIFIERS = MASK_SHIFT | MASK_CONTROL | MASK_OPTION | MASK_COMMAND

# клавиши, которые рвут слово: Enter, Tab, Esc, стрелки, Home/End/PgUp/PgDn
RESET_KEYS = {36, 76, 48, 53, 123, 124, 125, 126, 115, 116, 119, 121, 117}

# keycode модификатора -> (имя для core, его флаг)
MOD_KEYS = {56: ("shift", MASK_SHIFT), 60: ("shift", MASK_SHIFT),
            59: ("ctrl", MASK_CONTROL), 62: ("ctrl", MASK_CONTROL),
            58: ("alt", MASK_OPTION), 61: ("alt", MASK_OPTION)}

RU_SOURCE = "com.apple.keylayout.Russian"
EN_SOURCE = "com.apple.keylayout.US"

# ---------------------------------------------------- раскладки (Carbon TIS)

_carbon = ctypes.cdll.LoadLibrary(
    "/System/Library/Frameworks/Carbon.framework/Carbon")
_cf = ctypes.cdll.LoadLibrary(
    "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")

_cf.CFArrayGetCount.restype = ctypes.c_long
_cf.CFArrayGetCount.argtypes = [ctypes.c_void_p]
_cf.CFArrayGetValueAtIndex.restype = ctypes.c_void_p
_cf.CFArrayGetValueAtIndex.argtypes = [ctypes.c_void_p, ctypes.c_long]
_cf.CFStringGetCString.restype = ctypes.c_bool
_cf.CFStringGetCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                   ctypes.c_long, ctypes.c_uint32]
_cf.CFRelease.argtypes = [ctypes.c_void_p]
_cf.CFRetain.restype = ctypes.c_void_p
_cf.CFRetain.argtypes = [ctypes.c_void_p]

_carbon.TISCreateInputSourceList.restype = ctypes.c_void_p
_carbon.TISCreateInputSourceList.argtypes = [ctypes.c_void_p, ctypes.c_bool]
_carbon.TISGetInputSourceProperty.restype = ctypes.c_void_p
_carbon.TISGetInputSourceProperty.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_carbon.TISSelectInputSource.restype = ctypes.c_int
_carbon.TISSelectInputSource.argtypes = [ctypes.c_void_p]

_KEY_SOURCE_ID = ctypes.c_void_p.in_dll(_carbon, "kTISPropertyInputSourceID")


def _cfstr_to_str(ref):
    if not ref:
        return ""
    buf = ctypes.create_string_buffer(256)
    if _cf.CFStringGetCString(ref, buf, 256, 0x08000100):   # kCFStringEncodingUTF8
        return buf.value.decode("utf-8", "ignore")
    return ""


def input_sources():
    """{идентификатор раскладки: ссылка на источник ввода}."""
    lst = _carbon.TISCreateInputSourceList(None, False)
    out = {}
    if not lst:
        return out
    try:
        for i in range(_cf.CFArrayGetCount(lst)):
            src = _cf.CFArrayGetValueAtIndex(lst, i)
            name = _cfstr_to_str(_carbon.TISGetInputSourceProperty(src, _KEY_SOURCE_ID))
            if name:
                out.setdefault(name, src)
    finally:
        _cf.CFRelease(lst)
    return out


def find_layouts():
    """Ссылки на русскую и английскую раскладки, как их видит система."""
    sources = input_sources()
    found = {}
    for lang, exact, marks in (("ru", RU_SOURCE, ("Russian", "Cyrillic")),
                               ("en", EN_SOURCE, ("US", "ABC", "British"))):
        src = sources.get(exact)
        if src is None:                      # нестандартная раскладка - ищем по имени
            for name, ref in sources.items():
                if any(mark.lower() in name.lower() for mark in marks):
                    src = ref
                    break
        if src is not None:
            found[lang] = _cf.CFRetain(src)   # массив источников сейчас освободят
    return found


LAYOUTS = {}

# ------------------------------------------------------------------ ввод


def _post(event):
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)


def _tap_key(keycode, flags=0):
    for down in (True, False):
        evt = Quartz.CGEventCreateKeyboardEvent(None, keycode, down)
        if flags:
            Quartz.CGEventSetFlags(evt, flags)
        _post(evt)
        time.sleep(0.004)


def send_backspaces(n):
    for _ in range(n):
        _tap_key(KEY_BACKSPACE)


def send_text(text):
    """Печатает строку как есть - раскладка на результат не влияет."""
    for ch in text:
        for down in (True, False):
            evt = Quartz.CGEventCreateKeyboardEvent(None, 0, down)
            Quartz.CGEventKeyboardSetUnicodeString(evt, len(ch), ch)
            _post(evt)
        time.sleep(0.004)


def clipboard_get():
    pb = AppKit.NSPasteboard.generalPasteboard()
    return pb.stringForType_(AppKit.NSPasteboardTypeString) or ""


def clipboard_set(text):
    pb = AppKit.NSPasteboard.generalPasteboard()
    pb.clearContents()
    pb.setString_forType_(text, AppKit.NSPasteboardTypeString)


class MacBackend:
    """Системная часть для macOS."""

    def send_backspaces(self, n):
        send_backspaces(n)

    def send_text(self, text):
        send_text(text)

    def switch_layout(self, lang):
        src = LAYOUTS.get(lang)
        if src is not None:
            _carbon.TISSelectInputSource(src)

    def clipboard_get(self):
        return clipboard_get()

    def clipboard_set(self, text):
        clipboard_set(text)

    def copy_selection(self):
        _tap_key(KEY_C, MASK_COMMAND)
        time.sleep(0.15)
        return clipboard_get()

    def paste(self, text):
        clipboard_set(text)
        time.sleep(0.05)
        _tap_key(KEY_V, MASK_COMMAND)
        time.sleep(0.15)

    def wait_modifiers_up(self, timeout=1.0):
        end = time.time() + timeout
        while time.time() < end:
            flags = Quartz.CGEventSourceFlagsState(
                Quartz.kCGEventSourceStateCombinedSessionState)
            if not flags & MODIFIERS:
                return
            time.sleep(0.01)

    def front_app(self):
        app = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
        return app.processIdentifier() if app else None


SW = core.Switcher(MacBackend())

# ------------------------------------------------------------- перехват


class Hotkeys:
    """Разбор горячих клавиш, включая двойное нажатие модификатора."""

    def __init__(self, switcher, menu=None):
        self.sw = switcher
        self.menu = menu

    def refresh(self):
        if self.menu:
            self.menu.refresh()

    def on_flags_changed(self, event):
        """Двойное нажатие выбранного модификатора - перевести последнее слово."""
        flags = Quartz.CGEventGetFlags(event) & MODIFIERS
        keycode = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode)
        name, mask = MOD_KEYS.get(keycode, (None, 0))
        if name and not flags & mask:     # отпускание - для одиночного нажатия
            if self.sw.on_modifier_up(name):
                AppHelper.callLater(0.01, self.sw.convert_word)
            return False
        if not name:
            return False
        # нажат один этот модификатор; в сочетании с другими - сброс
        if self.sw.on_modifier(name if flags == mask else None):
            AppHelper.callLater(0.01, self.sw.convert_word)
        return False          # событие пропускаем дальше в любом случае

    def on_key(self, keycode, flags):
        """True, если событие наше и его нужно съесть."""
        if not (flags & MASK_CONTROL and flags & MASK_OPTION):
            return False
        shift = bool(flags & MASK_SHIFT)
        if keycode == KEY_L:
            AppHelper.callLater(0.01,
                                self.sw.convert_selection if shift else self.sw.convert_word)
        elif keycode == KEY_S:
            AppHelper.callLater(0.01, self.sw.spell_word)
        elif keycode == KEY_A:
            self.sw.toggle_auto()
            self.refresh()
        elif keycode == KEY_P:
            self.sw.toggle_spell()
            self.refresh()
        elif keycode == KEY_Q:
            AppHelper.stopEventLoop()
        else:
            return False
        return True


HOTKEYS = Hotkeys(SW)


def event_char(event):
    """Символ, который дала бы эта клавиша в текущей раскладке."""
    try:
        result = Quartz.CGEventKeyboardGetUnicodeString(event, 4, None, None)
    except Exception:
        return ""
    if not isinstance(result, tuple):
        return ""
    # в разных версиях pyobjc это (длина, строка) либо (None, длина, строка)
    chars = ""
    for value in result:
        if isinstance(value, str) and value:
            chars = value
    if not chars:
        return ""
    ch = chars[0]
    return ch if ch.isprintable() or ch.isspace() else ""


def tap_callback(proxy, type_, event, refcon):
    # система может отключить tap при перегрузке - включаем обратно
    if type_ in (Quartz.kCGEventTapDisabledByTimeout,
                 Quartz.kCGEventTapDisabledByUserInput):
        Quartz.CGEventTapEnable(TAP[0], True)
        return event

    if type_ == Quartz.kCGEventFlagsChanged:
        HOTKEYS.on_flags_changed(event)
        return event

    if type_ != Quartz.kCGEventKeyDown:
        return event

    keycode = Quartz.CGEventGetIntegerValueField(
        event, Quartz.kCGKeyboardEventKeycode)
    flags = Quartz.CGEventGetFlags(event)

    HOTKEYS.last_shift = 0.0              # между двумя Shift ничего не печатали

    if HOTKEYS.on_key(keycode, flags):
        return None                       # съедаем наше сочетание

    if SW.injecting:
        return event
    if keycode in RESET_KEYS:
        SW.reset()
        return event
    if keycode == KEY_BACKSPACE:
        SW.on_backspace()
        return event
    if flags & (MASK_COMMAND | MASK_CONTROL | MASK_OPTION):
        SW.reset()
        return event

    ch = event_char(event)
    if ch and SW.on_char(ch):
        # слово дописано; даём нажатому пробелу дойти до программы
        AppHelper.callLater(0.05, SW.auto_fix)
    return event


TAP = [None]

# --------------------------------------------------------- значок в меню


TRIGGER_NAMES = {"ctrl": "⌃ Control", "alt": "⌥ Option", "shift": "⇧ Shift",
                 "space": "Пробел", "off": "Выключено"}
TAPS_NAMES = {1: "1 - одно нажатие", 2: "2 - два нажатия"}


class MenuDelegate(AppKit.NSObject):
    """Значок в строке меню: состояние и переключатели."""

    def initWithSwitcher_(self, switcher):
        self = objc.super(MenuDelegate, self).init()
        if self is None:
            return None
        self.sw = switcher
        bar = AppKit.NSStatusBar.systemStatusBar()
        self.item = bar.statusItemWithLength_(AppKit.NSVariableStatusItemLength)
        self.menu = AppKit.NSMenu.alloc().init()

        self.auto_item = self._add("Авто-раскладка (⌃⌥A)", "toggleAuto:")
        self.spell_item = self._add("Авто-орфография (⌃⌥P)", "toggleSpell:")
        self.menu.addItem_(AppKit.NSMenuItem.separatorItem())
        self.trigger_root = self._add("Перевод слова", None)
        self.trigger_menu = AppKit.NSMenu.alloc().init()
        self.trigger_items = []
        self.taps_items = []
        for taps in core.TAPS:
            item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                TAPS_NAMES[taps], "setTaps:", "")
            item.setTarget_(self)
            item.setTag_(taps)
            self.trigger_menu.addItem_(item)
            self.taps_items.append(item)
        self.trigger_menu.addItem_(AppKit.NSMenuItem.separatorItem())
        self.trigger_menu.setAutoenablesItems_(False)
        for i, trig in enumerate(core.TRIGGERS):
            item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                TRIGGER_NAMES[trig], "setTrigger:", "")
            item.setTarget_(self)
            item.setTag_(i)
            self.trigger_menu.addItem_(item)
            self.trigger_items.append(item)
        self.trigger_root.setSubmenu_(self.trigger_menu)
        self._add("Слово в другую раскладку (⌃⌥L)", "convertWord:")
        self._add("Выделенное в другую раскладку (⌃⌥⇧L)", "convertSelection:")
        self._add("Исправить опечатку (⌃⌥S)", "spellWord:")
        self.menu.addItem_(AppKit.NSMenuItem.separatorItem())
        self._add("Выход (⌃⌥Q)", "quit:")

        self.item.setMenu_(self.menu)
        self.refresh()
        return self

    def _add(self, title, selector):
        item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            title, selector, "")
        item.setTarget_(self)
        self.menu.addItem_(item)
        return item

    def refresh(self):
        self.auto_item.setState_(1 if self.sw.auto else 0)
        self.spell_item.setState_(1 if self.sw.auto_spell else 0)
        for trig, item in zip(core.TRIGGERS, self.trigger_items):
            item.setState_(1 if self.sw.trigger == trig else 0)
            item.setEnabled_(not (trig == "space" and self.sw.taps == 1))
        for taps, item in zip(core.TAPS, self.taps_items):
            item.setState_(1 if self.sw.taps == taps else 0)
        if self.sw.trigger == "off":
            self.trigger_root.setTitle_("Перевод слова: выключен")
        else:
            self.trigger_root.setTitle_(
                f"Перевод слова: {self.sw.taps}× {TRIGGER_NAMES[self.sw.trigger]}")
        title = "ПА" if self.sw.auto else "П"
        self.item.button().setTitle_(title)
        self.item.button().setToolTip_(self.sw.status())

    def toggleAuto_(self, sender):
        self.sw.toggle_auto()
        self.refresh()

    def toggleSpell_(self, sender):
        self.sw.toggle_spell()
        self.refresh()

    def setTaps_(self, sender):
        self.sw.set_taps(sender.tag())
        self.refresh()

    def setTrigger_(self, sender):
        self.sw.set_trigger(core.TRIGGERS[sender.tag()])
        self.refresh()

    def convertWord_(self, sender):
        self.sw.convert_word()

    def convertSelection_(self, sender):
        self.sw.convert_selection()

    def spellWord_(self, sender):
        self.sw.spell_word()

    def quit_(self, sender):
        AppHelper.stopEventLoop()


# ------------------------------------------------------------------ запуск


def has_access():
    """Есть ли разрешение слушать клавиатуру (на старых macOS функции нет)."""
    preflight = getattr(Quartz, "CGPreflightListenEventAccess", None)
    return bool(preflight()) if preflight else True


def request_access():
    request = getattr(Quartz, "CGRequestListenEventAccess", None)
    if request:
        request()


def check():
    """Диагностика: права, раскладки, словари - без перехвата клавиш."""
    trusted = has_access()
    print("доступ к событиям клавиатуры:", "есть" if trusted else "НЕТ")
    if not trusted:
        print("  Системные настройки -> Конфиденциальность и безопасность ->"
              " Универсальный доступ: добавить Терминал (или python3)")
    sources = input_sources()
    print("раскладок в системе:", len(sources))
    found = find_layouts()
    for lang in ("ru", "en"):
        print(f"  {lang}: {'найдена' if lang in found else 'НЕ НАЙДЕНА'}")
    if len(found) < 2:
        print("  добавьте обе раскладки в Системных настройках -> Клавиатура")

    from layouts import convert, looks_wrong
    import spell
    print("проверка логики:",
          convert("ghbdtn"), "|", looks_wrong("ghbdtn"), "|", spell.suggest("привте"))
    return trusted and len(found) == 2


def main(argv):
    global LAYOUTS, HOTKEYS

    if "--check" in argv:
        return 0 if check() else 1

    LAYOUTS = find_layouts()
    if len(LAYOUTS) < 2:
        print("Нужны обе раскладки - русская и английская. Запустите с --check.")
        return 1
    if not has_access():
        request_access()
        print("Нет доступа к клавиатуре. Разрешите его в Системных настройках"
              " -> Конфиденциальность -> Универсальный доступ и запустите снова.")
        return 1

    SW.auto = "--auto" in argv
    SW.auto_spell = "--spell" in argv
    SW.apply_settings(core.load_settings(), "space")
    if "--no-double-space" in argv:
        SW.trigger = "off"

    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
    menu = MenuDelegate.alloc().initWithSwitcher_(SW)
    HOTKEYS = Hotkeys(SW, menu)

    mask = (Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown) |
            Quartz.CGEventMaskBit(Quartz.kCGEventFlagsChanged))
    tap = Quartz.CGEventTapCreate(
        Quartz.kCGSessionEventTap, Quartz.kCGHeadInsertEventTap,
        Quartz.kCGEventTapOptionDefault, mask, tap_callback, None)
    if not tap:
        print("Не удалось поставить перехват клавиш - нет прав доступа.")
        return 1
    TAP[0] = tap
    source = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
    Quartz.CFRunLoopAddSource(Quartz.CFRunLoopGetCurrent(), source,
                              Quartz.kCFRunLoopCommonModes)
    Quartz.CGEventTapEnable(tap, True)

    print("Запущено. Двойной пробел (см. меню) - раскладка слова, ⌃⌥⇧L - выделенное, "
          "⌃⌥S - орфография, ⌃⌥A - авто-режим, ⌃⌥Q - выход.")
    AppHelper.runEventLoop()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
