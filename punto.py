# -*- coding: utf-8 -*-
"""
Tilashar - переключатель раскладки в духе Punto Switcher (RU <-> EN), Windows.

Горячие клавиши:
    Pause/Break        - перевести последнее набранное слово в другую раскладку
    Shift+Pause        - перевести выделенный текст (через буфер обмена)
    Ctrl+Alt+Pause     - исправить опечатку в последнем слове
    Ctrl+Pause         - вкл/выкл автоматический режим
    Ctrl+Shift+Pause   - выход

Зависимостей нет, только ctypes. Запуск: py punto.py (или punto.bat - без консоли),
либо Tilashar.exe (собирается build-exe.bat), который умеет обновляться с GitHub.
"""

import ctypes
import ctypes.wintypes as w
import os
import sys
import threading
import time
import winreg

import core
import updater
from version import VERSION
from layouts import detect_direction, HERE, RU_LCID, EN_LCID

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)

# ---------------------------------------------------------------- WinAPI

IS64 = ctypes.sizeof(ctypes.c_void_p) == 8
ULONG_PTR = ctypes.c_ulonglong if IS64 else ctypes.c_ulong
LRESULT = ctypes.c_longlong if IS64 else ctypes.c_long

WH_KEYBOARD_LL, WH_MOUSE_LL = 13, 14
WM_KEYDOWN, WM_SYSKEYDOWN = 0x0100, 0x0104
WM_KEYUP, WM_SYSKEYUP = 0x0101, 0x0105
WM_LBUTTONDOWN, WM_RBUTTONDOWN = 0x0201, 0x0204
WM_DESTROY, WM_COMMAND, WM_HOTKEY = 0x0002, 0x0111, 0x0312
WM_INPUTLANGCHANGEREQUEST = 0x0050
WM_RBUTTONUP, WM_LBUTTONDBLCLK = 0x0205, 0x0203
WM_TRAY = 0x0400 + 1
WM_AUTOFIX = 0x0400 + 2   # «проверь последнее слово» - из хука в главный поток
WM_CONVERT = 0x0400 + 3   # «переведи последнее слово» - двойной Ctrl/Alt/Shift
WM_UPDATE = 0x0400 + 4    # проверка обновлений: wparam=1 - начать, 0 - готов результат
WM_UPDATE_READY = 0x0400 + 5   # новый exe скачан, пора перезапускаться
WM_CLOSE = 0x0010

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 0x0002, 0x0004
LLKHF_INJECTED = 0x10

MOD_ALT, MOD_CONTROL, MOD_SHIFT = 0x0001, 0x0002, 0x0004
VK_BACK, VK_SHIFT, VK_CONTROL, VK_MENU, VK_CAPITAL, VK_PAUSE = 0x08, 0x10, 0x11, 0x12, 0x14, 0x13
VK_LWIN, VK_RWIN, VK_C, VK_V = 0x5B, 0x5C, 0x43, 0x56

# модификаторы для двойного нажатия: хук видит левые/правые коды
MOD_KEYS = {VK_SHIFT: "shift", 0xA0: "shift", 0xA1: "shift",
            VK_CONTROL: "ctrl", 0xA2: "ctrl", 0xA3: "ctrl",
            VK_MENU: "alt", 0xA4: "alt", 0xA5: "alt"}
HELD = set()          # модификаторы, которые сейчас зажаты

# PUNTO_TEST=1 - учитывать синтетический ввод (нужно для автотестов)
ALLOW_INJECTED = os.environ.get("PUNTO_TEST") == "1"

# клавиши, которые рвут "слово" и сбрасывают буфер
RESET_KEYS = {
    0x0D, 0x09, 0x1B,                    # Enter, Tab, Esc
    0x25, 0x26, 0x27, 0x28,              # стрелки
    0x21, 0x22, 0x23, 0x24, 0x2E, 0x2D,  # PgUp/PgDn/End/Home/Del/Ins
}


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", w.DWORD), ("scanCode", w.DWORD), ("flags", w.DWORD),
                ("time", w.DWORD), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", w.WORD), ("wScan", w.WORD), ("dwFlags", w.DWORD),
                ("time", w.DWORD), ("dwExtraInfo", ULONG_PTR)]


class _INPUTUNION(ctypes.Union):
    # размер union задаёт MOUSEINPUT (32 байта на x64), иначе SendInput вернёт
    # ERROR_INVALID_PARAMETER из-за неверного cbSize
    _fields_ = [("ki", KEYBDINPUT), ("pad", ctypes.c_byte * 32)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", w.DWORD), ("u", _INPUTUNION)]


class NOTIFYICONDATA(ctypes.Structure):
    _fields_ = [("cbSize", w.DWORD), ("hWnd", w.HWND), ("uID", w.UINT),
                ("uFlags", w.UINT), ("uCallbackMessage", w.UINT), ("hIcon", w.HANDLE),
                ("szTip", w.WCHAR * 128), ("dwState", w.DWORD), ("dwStateMask", w.DWORD),
                ("szInfo", w.WCHAR * 256), ("uVersion", w.UINT),
                ("szInfoTitle", w.WCHAR * 64), ("dwInfoFlags", w.DWORD)]


WNDPROC = ctypes.WINFUNCTYPE(LRESULT, w.HWND, w.UINT, w.WPARAM, w.LPARAM)
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, w.WPARAM, w.LPARAM)


class WNDCLASS(ctypes.Structure):
    _fields_ = [("style", w.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", w.HINSTANCE), ("hIcon", w.HANDLE),
                ("hCursor", w.HANDLE), ("hbrBackground", w.HANDLE),
                ("lpszMenuName", w.LPCWSTR), ("lpszClassName", w.LPCWSTR)]


# прототипы обязательны: иначе ctypes режет 64-битные хэндлы до int
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, w.HINSTANCE, w.DWORD]
user32.SetWindowsHookExW.restype = w.HHOOK
user32.UnhookWindowsHookEx.argtypes = [w.HHOOK]
user32.CallNextHookEx.argtypes = [w.HHOOK, ctypes.c_int, w.WPARAM, w.LPARAM]
user32.CallNextHookEx.restype = LRESULT
user32.DefWindowProcW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.PostMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
user32.SendMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
user32.SendMessageW.restype = LRESULT
user32.GetForegroundWindow.restype = w.HWND
user32.SetForegroundWindow.argtypes = [w.HWND]
user32.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.c_void_p]
user32.GetWindowThreadProcessId.restype = w.DWORD
user32.GetKeyboardLayout.argtypes = [w.DWORD]
user32.GetKeyboardLayout.restype = w.HKL
user32.GetKeyboardLayoutList.argtypes = [ctypes.c_int, ctypes.c_void_p]
user32.CreateWindowExW.argtypes = [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   w.HWND, w.HMENU, w.HINSTANCE, ctypes.c_void_p]
user32.CreateWindowExW.restype = w.HWND
user32.LoadIconW.argtypes = [w.HINSTANCE, w.LPCWSTR]
user32.LoadIconW.restype = w.HANDLE
user32.LoadImageW.argtypes = [w.HINSTANCE, w.LPCWSTR, w.UINT, ctypes.c_int, ctypes.c_int, w.UINT]
user32.LoadImageW.restype = w.HANDLE
user32.CreatePopupMenu.restype = w.HMENU
user32.AppendMenuW.argtypes = [w.HMENU, w.UINT, ctypes.c_void_p, w.LPCWSTR]
user32.TrackPopupMenu.argtypes = [w.HMENU, w.UINT, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, w.HWND, ctypes.c_void_p]
user32.DestroyMenu.argtypes = [w.HMENU]
user32.RegisterHotKey.argtypes = [w.HWND, ctypes.c_int, w.UINT, w.UINT]
user32.SendInput.argtypes = [w.UINT, ctypes.c_void_p, ctypes.c_int]
user32.ToUnicodeEx.argtypes = [w.UINT, w.UINT, ctypes.c_void_p, w.LPWSTR,
                               ctypes.c_int, w.UINT, w.HKL]
user32.GetClipboardData.argtypes = [w.UINT]
user32.GetClipboardData.restype = w.HANDLE
user32.SetClipboardData.argtypes = [w.UINT, w.HANDLE]
user32.SetClipboardData.restype = w.HANDLE
user32.OpenClipboard.argtypes = [w.HWND]
user32.MessageBoxW.argtypes = [w.HWND, w.LPCWSTR, w.LPCWSTR, w.UINT]
user32.FindWindowW.argtypes = [w.LPCWSTR, w.LPCWSTR]
user32.FindWindowW.restype = w.HWND
user32.IsWindow.argtypes = [w.HWND]
kernel32.GetModuleHandleW.argtypes = [w.LPCWSTR]
kernel32.GetModuleHandleW.restype = w.HMODULE
kernel32.GlobalAlloc.argtypes = [w.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = w.HANDLE
kernel32.GlobalLock.argtypes = [w.HANDLE]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [w.HANDLE]
shell32.Shell_NotifyIconW.argtypes = [w.DWORD, ctypes.c_void_p]

# ---------------------------------------------------------------- утилиты


def foreground_hwnd_hkl():
    hwnd = user32.GetForegroundWindow()
    tid = user32.GetWindowThreadProcessId(hwnd, None)
    return hwnd, user32.GetKeyboardLayout(tid)


def layout_list():
    """{lcid: hkl} установленных раскладок."""
    n = user32.GetKeyboardLayoutList(0, None)
    arr = (w.HKL * max(n, 1))()
    user32.GetKeyboardLayoutList(n, arr)
    out = {}
    for hkl in arr[:n]:
        out.setdefault(hkl & 0xFFFF, hkl)
    return out


LAYOUTS = layout_list()


def layout_for(text):
    """Раскладка, в которой набран этот текст: кириллица - русская, иначе US."""
    return RU_LCID if detect_direction(text) == "ru2en" else EN_LCID


def switch_layout(lcid):
    hkl = LAYOUTS.get(lcid)
    if hkl:
        user32.PostMessageW(user32.GetForegroundWindow(),
                            WM_INPUTLANGCHANGEREQUEST, 0, hkl)


def _key(vk, up=False):
    return INPUT(type=INPUT_KEYBOARD,
                 u=_INPUTUNION(ki=KEYBDINPUT(wVk=vk, wScan=0,
                                             dwFlags=KEYEVENTF_KEYUP if up else 0,
                                             time=0, dwExtraInfo=0)))


def _char(ch, up=False):
    flags = KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if up else 0)
    return INPUT(type=INPUT_KEYBOARD,
                 u=_INPUTUNION(ki=KEYBDINPUT(wVk=0, wScan=ord(ch),
                                             dwFlags=flags, time=0, dwExtraInfo=0)))


def send_inputs(items):
    if not items:
        return
    arr = (INPUT * len(items))(*items)
    user32.SendInput(len(items), ctypes.byref(arr), ctypes.sizeof(INPUT))


def send_backspaces(n):
    send_inputs([x for _ in range(n) for x in (_key(VK_BACK), _key(VK_BACK, True))])


def send_text(text):
    # шлём юникодом - не зависит от того, какая раскладка активна
    send_inputs([x for ch in text for x in (_char(ch), _char(ch, True))])


def send_combo(mod_vk, vk):
    send_inputs([_key(mod_vk), _key(vk), _key(vk, True), _key(mod_vk, True)])


def wait_modifiers_up(timeout=1.0):
    """Ждём отпускания модификаторов, иначе они прилипнут к нашему вводу."""
    end = time.time() + timeout
    while time.time() < end:
        if not any(user32.GetAsyncKeyState(vk) & 0x8000
                   for vk in (VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN)):
            return
        time.sleep(0.01)


# ---------------------------------------------------------------- буфер обмена

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002


def clipboard_get():
    if not user32.OpenClipboard(None):
        return ""
    try:
        h = user32.GetClipboardData(CF_UNICODETEXT)
        if not h:
            return ""
        p = kernel32.GlobalLock(h)
        try:
            return ctypes.c_wchar_p(p).value or ""
        finally:
            kernel32.GlobalUnlock(h)
    finally:
        user32.CloseClipboard()


def clipboard_set(text):
    if not user32.OpenClipboard(None):
        return False
    try:
        user32.EmptyClipboard()
        buf = ctypes.create_unicode_buffer(text)
        size = ctypes.sizeof(buf)
        h = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
        p = kernel32.GlobalLock(h)
        ctypes.memmove(p, buf, size)
        kernel32.GlobalUnlock(h)
        user32.SetClipboardData(CF_UNICODETEXT, h)
        return True
    finally:
        user32.CloseClipboard()


# ---------------------------------------------------------------- логика

class WinBackend:
    """Системная часть для Windows: ввод, раскладки, буфер обмена."""

    def send_backspaces(self, n):
        send_backspaces(n)

    def send_text(self, text):
        send_text(text)

    def switch_layout(self, lang):
        switch_layout(RU_LCID if lang == "ru" else EN_LCID)

    def clipboard_get(self):
        return clipboard_get()

    def clipboard_set(self, text):
        clipboard_set(text)

    def copy_selection(self):
        send_combo(VK_CONTROL, VK_C)
        time.sleep(0.15)
        return clipboard_get()

    def paste(self, text):
        clipboard_set(text)
        time.sleep(0.05)
        send_combo(VK_CONTROL, VK_V)
        time.sleep(0.15)

    def wait_modifiers_up(self):
        wait_modifiers_up()

    def front_app(self):
        return user32.GetForegroundWindow()


def vk_to_char(vk, scan, hkl):
    """Символ, который дала бы эта клавиша в раскладке активного окна."""
    state = (ctypes.c_ubyte * 256)()
    if user32.GetKeyState(VK_SHIFT) & 0x8000:
        state[VK_SHIFT] = 0x80
    if user32.GetKeyState(VK_CAPITAL) & 0x0001:
        state[VK_CAPITAL] = 0x01
    buf = ctypes.create_unicode_buffer(8)
    n = user32.ToUnicodeEx(vk, scan, state, buf, 8, 0, hkl)
    if n <= 0:
        return ""
    ch = buf[n - 1]
    return ch if ch.isprintable() or ch.isspace() else ""


def on_modifier_key(vk, up):
    """Ctrl/Alt/Shift: считаем только нажатие без других модификаторов и без автоповтора.

    Возвращает True, если событие надо съесть (отпускание Alt, см. ниже).
    """
    if up:
        HELD.discard(vk)
        if not SW.on_modifier_up(MOD_KEYS[vk]) or not MAIN_HWND[0]:
            return False
        user32.PostMessageW(MAIN_HWND[0], WM_CONVERT, 0, 0)
        if MOD_KEYS[vk] != "alt":
            return False
        # одиночный Alt открыл бы строку меню окна. Съедаем настоящее отпускание
        # и посылаем Ctrl + отпускание Alt: система видит сочетание, меню молчит
        send_inputs([_key(VK_CONTROL), _key(VK_CONTROL, True), _key(vk, True)])
        return True
    if vk in HELD:                         # автоповтор зажатой клавиши
        return False
    # отпускание могло потеряться (Win+L и т.п.) - сверяемся с системой
    HELD.intersection_update({k for k in HELD if user32.GetAsyncKeyState(k) & 0x8000})
    alone = not HELD
    HELD.add(vk)
    if SW.on_modifier(MOD_KEYS[vk] if alone else None) and MAIN_HWND[0]:
        user32.PostMessageW(MAIN_HWND[0], WM_CONVERT, 0, 0)
    return False


def on_key(vk, scan, flags, up=False):
    """Разбор нажатия из хука; тяжёлую проверку откладываем в главный поток.

    True - событие съесть, дальше не передавать.
    """
    if SW.injecting or (flags & LLKHF_INJECTED and not ALLOW_INJECTED):
        return False
    if vk in MOD_KEYS:
        return on_modifier_key(vk, up)
    if up:
        return
    if vk in RESET_KEYS:
        SW.reset()
        return
    if vk == VK_BACK:
        SW.on_backspace()
        return
    if user32.GetAsyncKeyState(VK_CONTROL) & 0x8000 or user32.GetAsyncKeyState(VK_MENU) & 0x8000:
        SW.reset()
        return
    hwnd, hkl = foreground_hwnd_hkl()
    ch = vk_to_char(vk, scan, hkl)
    if ch and SW.on_char(ch) and MAIN_HWND[0]:
        user32.PostMessageW(MAIN_HWND[0], WM_AUTOFIX, 0, 0)


SW = core.Switcher(WinBackend())
MAIN_HWND = [None]   # hwnd служебного окна; заполняется в main()

# ---------------------------------------------------------------- хуки


@HOOKPROC
def keyboard_proc(code, wparam, lparam):
    if code == 0 and wparam in (WM_KEYDOWN, WM_SYSKEYDOWN, WM_KEYUP, WM_SYSKEYUP):
        kb = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
        try:
            if on_key(kb.vkCode, kb.scanCode, kb.flags, wparam in (WM_KEYUP, WM_SYSKEYUP)):
                return 1
        except Exception:
            pass
    return user32.CallNextHookEx(None, code, wparam, lparam)


@HOOKPROC
def mouse_proc(code, wparam, lparam):
    if code == 0 and wparam in (WM_LBUTTONDOWN, WM_RBUTTONDOWN):
        SW.reset()
    return user32.CallNextHookEx(None, code, wparam, lparam)


# ---------------------------------------------------------------- трей и окно

NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP = 0x01, 0x02, 0x04
IDI_APPLICATION = 32512
MF_STRING, MF_SEPARATOR, MF_CHECKED, MF_POPUP, MF_GRAYED = 0x0000, 0x0800, 0x0008, 0x0010, 0x0001
TPM_RIGHTBUTTON = 0x0002

ID_AUTO, ID_SPELL, ID_EXIT = 1001, 1003, 1002
ID_AUTOUPDATE, ID_CHECKUPDATE, ID_AUTOSTART = 1004, 1005, 1006
ID_TRIGGER = 1100     # + номер в core.TRIGGERS
DEFAULT_TRIGGER = "ctrl"   # пока в меню ничего не выбрано
ID_TAPS = 1200        # + число нажатий
TRIGGER_NAMES = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift",
                 "space": "Пробел", "off": "Выключено"}
TAPS_NAMES = {1: "1 - одно нажатие", 2: "2 - два нажатия"}


def trigger_title():
    if SW.trigger == "off":
        return "Перевод слова: выключен"
    return f"Перевод слова: {SW.taps}× {TRIGGER_NAMES[SW.trigger]}"
HK_WORD, HK_SEL, HK_AUTO, HK_EXIT, HK_SPELL = 1, 2, 3, 4, 5

nid = NOTIFYICONDATA()


def tray_tip():
    return SW.status() + " " + VERSION


# ---------------------------------------------------------------- обновления

MB_OK, MB_YESNO, IDYES = 0x0, 0x4, 6
MB_ICONINFO, MB_ICONQUESTION, MB_ICONWARNING = 0x40, 0x20, 0x30
MB_SETFOREGROUND, MB_TOPMOST = 0x10000, 0x40000
UPDATE_EVERY = 24 * 3600      # как часто проверять в фоне, сек
UPDATE = {"busy": False, "manual": False, "info": None, "error": None, "path": None}


def message(text, flags=MB_OK | MB_ICONINFO):
    return user32.MessageBoxW(MAIN_HWND[0], text, core.APP_NAME,
                              flags | MB_SETFOREGROUND | MB_TOPMOST)


def check_updates(manual):
    """Проверка в фоновом потоке: сеть не должна тормозить хук клавиатуры."""
    if UPDATE["busy"]:
        return
    if not updater.frozen():
        if manual:
            message("Обновление работает только в Tilashar.exe.\n"
                    "Скриптовую версию обновляйте через git pull.")
        return
    UPDATE.update(busy=True, manual=manual, info=None, error=None)

    def work():
        try:
            UPDATE["info"] = updater.check()
        except Exception as exc:          # нет сети, GitHub недоступен и т.п.
            UPDATE["error"] = str(exc)
        user32.PostMessageW(MAIN_HWND[0], WM_UPDATE, 0, 0)

    threading.Thread(target=work, daemon=True).start()


def on_update_checked():
    info, manual = UPDATE["info"], UPDATE["manual"]
    UPDATE["busy"] = False
    if UPDATE["error"]:
        if manual:
            message("Не удалось проверить обновления:\n" + UPDATE["error"],
                    MB_OK | MB_ICONWARNING)
        return
    if not info:
        if manual:
            message(f"У вас последняя версия ({VERSION}).")
        return
    if not manual and core.load_settings().get("skip_version") == info["version"]:
        return                            # от этой версии уже отказались
    answer = message(f"Вышла версия {info['version']} (у вас {VERSION}).\n"
                     "Скачать и перезапустить программу?", MB_YESNO | MB_ICONQUESTION)
    if answer != IDYES:
        core.save_settings(skip_version=info["version"])
        return
    UPDATE.update(busy=True, error=None, path=None)

    def work():
        try:
            UPDATE["path"] = updater.download(info)
        except Exception as exc:
            UPDATE["error"] = str(exc)
        user32.PostMessageW(MAIN_HWND[0], WM_UPDATE_READY, 0, 0)

    threading.Thread(target=work, daemon=True).start()


def on_update_downloaded():
    UPDATE["busy"] = False
    if UPDATE["error"] or not UPDATE["path"]:
        message("Не удалось скачать обновление:\n" + str(UPDATE["error"]),
                MB_OK | MB_ICONWARNING)
        return
    try:
        updater.install_and_restart(UPDATE["path"])
    except OSError as exc:
        message("Не удалось установить обновление:\n" + str(exc), MB_OK | MB_ICONWARNING)
        return
    user32.PostQuitMessage(0)


def auto_update_loop():
    """Фоновая проверка: через минуту после запуска и дальше раз в сутки."""
    time.sleep(60)
    while True:
        if core.load_settings().get("auto_update", True) and MAIN_HWND[0]:
            user32.PostMessageW(MAIN_HWND[0], WM_UPDATE, 1, 0)
        time.sleep(UPDATE_EVERY)


def toggle_auto_update():
    core.save_settings(auto_update=not core.load_settings().get("auto_update", True))


# ---------------------------------------------------------------- автозапуск
# То же значение пишет установщик (галочка «Запускать при входе в Windows»).

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def autostart_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, core.APP_NAME)
        return True
    except OSError:
        return False


def toggle_autostart():
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if autostart_enabled():
            winreg.DeleteValue(key, core.APP_NAME)
        else:
            winreg.SetValueEx(key, core.APP_NAME, 0, winreg.REG_SZ, f'"{sys.executable}"')


def load_tray_icon():
    """Значок-диафрагма tilashar.ico; если файла нет - стандартный."""
    path = os.path.join(HERE, "tilashar.ico")
    size = user32.GetSystemMetrics(49)            # SM_CXSMICON - размер значка в трее
    icon = user32.LoadImageW(None, path, 1, size, size, 0x10)   # IMAGE_ICON, LR_LOADFROMFILE
    return icon or user32.LoadIconW(None, ctypes.cast(ctypes.c_void_p(IDI_APPLICATION), w.LPCWSTR))


def close_other_copy():
    """Закрыть уже запущенную копию (скрипт или exe), чтобы не было двух хуков."""
    other = user32.FindWindowW("PuntoPyWnd", None)
    if not other:
        return
    user32.PostMessageW(other, WM_CLOSE, 0, 0)
    for _ in range(50):
        time.sleep(0.1)
        if not user32.IsWindow(other):
            return


def tray_update():
    nid.uFlags = NIF_TIP
    nid.szTip = tray_tip()
    shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))


def toggle_auto():
    SW.toggle_auto()
    tray_update()


def toggle_spell():
    SW.toggle_spell()
    tray_update()


def show_menu(hwnd):
    menu = user32.CreatePopupMenu()
    user32.AppendMenuW(menu, MF_STRING | (MF_CHECKED if SW.auto else 0), ID_AUTO,
                       "Авто-режим (Ctrl+Pause)")
    user32.AppendMenuW(menu, MF_STRING | (MF_CHECKED if SW.auto_spell else 0), ID_SPELL,
                       "Авто-орфография")
    sub = user32.CreatePopupMenu()
    for taps in core.TAPS:
        user32.AppendMenuW(sub, MF_STRING | (MF_CHECKED if SW.taps == taps else 0),
                           ID_TAPS + taps, TAPS_NAMES[taps])
    user32.AppendMenuW(sub, MF_SEPARATOR, 0, None)
    for i, trig in enumerate(core.TRIGGERS):
        if trig == "off":
            user32.AppendMenuW(sub, MF_SEPARATOR, 0, None)
        flags = MF_CHECKED if SW.trigger == trig else 0
        if trig == "space" and SW.taps == 1:
            flags |= MF_GRAYED             # одиночный пробел переводил бы каждое слово
        user32.AppendMenuW(sub, MF_STRING | flags, ID_TRIGGER + i, TRIGGER_NAMES[trig])
    user32.AppendMenuW(menu, MF_POPUP, sub, trigger_title())
    user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
    auto_update = core.load_settings().get("auto_update", True)
    user32.AppendMenuW(menu, MF_STRING | (MF_CHECKED if auto_update else 0), ID_AUTOUPDATE,
                       "Автообновление")
    user32.AppendMenuW(menu, MF_STRING, ID_CHECKUPDATE,
                       f"Проверить обновления (версия {VERSION})")
    if updater.frozen():                  # скриптовую версию ставит в автозагрузку install-windows
        user32.AppendMenuW(menu, MF_STRING | (MF_CHECKED if autostart_enabled() else 0),
                           ID_AUTOSTART, "Запускать вместе с Windows")
    user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
    user32.AppendMenuW(menu, MF_STRING, ID_EXIT, "Выход")
    pt = w.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    user32.SetForegroundWindow(hwnd)
    user32.TrackPopupMenu(menu, TPM_RIGHTBUTTON, pt.x, pt.y, 0, hwnd, None)
    user32.PostMessageW(hwnd, 0, 0, 0)
    user32.DestroyMenu(menu)


@WNDPROC
def wnd_proc(hwnd, msg, wparam, lparam):
    if msg == WM_HOTKEY:
        if wparam == HK_WORD:
            SW.convert_word()
        elif wparam == HK_SEL:
            SW.convert_selection()
        elif wparam == HK_AUTO:
            toggle_auto()
        elif wparam == HK_SPELL:
            SW.spell_word()
        elif wparam == HK_EXIT:
            user32.PostQuitMessage(0)
        return 0
    if msg == WM_UPDATE:
        if wparam:
            check_updates(manual=False)
        else:
            on_update_checked()
        return 0
    if msg == WM_UPDATE_READY:
        on_update_downloaded()
        return 0
    if msg == WM_CONVERT:
        SW.convert_word()
        return 0
    if msg == WM_AUTOFIX:
        time.sleep(0.05)          # даём нажатому пробелу дойти до приложения
        SW.auto_fix()
        return 0
    if msg == WM_TRAY:
        if lparam == WM_RBUTTONUP:
            show_menu(hwnd)
        elif lparam == WM_LBUTTONDBLCLK:
            toggle_auto()
        return 0
    if msg == WM_COMMAND:
        cid = wparam & 0xFFFF
        if cid == ID_AUTO:
            toggle_auto()
        elif cid == ID_SPELL:
            toggle_spell()
        elif cid == ID_AUTOUPDATE:
            toggle_auto_update()
        elif cid == ID_CHECKUPDATE:
            check_updates(manual=True)
        elif cid == ID_AUTOSTART:
            try:
                toggle_autostart()
            except OSError as exc:
                message("Не удалось изменить автозапуск:\n" + str(exc), MB_OK | MB_ICONWARNING)
        elif cid - ID_TAPS in core.TAPS:
            SW.set_taps(cid - ID_TAPS)
        elif ID_TRIGGER <= cid < ID_TRIGGER + len(core.TRIGGERS):
            SW.set_trigger(core.TRIGGERS[cid - ID_TRIGGER])
        elif cid == ID_EXIT:
            user32.PostQuitMessage(0)
        return 0
    if msg == WM_DESTROY:
        user32.PostQuitMessage(0)
        return 0
    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)


def main():
    if RU_LCID not in LAYOUTS or EN_LCID not in LAYOUTS:
        print("Нужны обе раскладки - русская и английская.")
        return 1

    hinst = kernel32.GetModuleHandleW(None)
    close_other_copy()
    updater.cleanup()

    cls = WNDCLASS()
    cls.lpfnWndProc = wnd_proc
    cls.hInstance = hinst
    cls.lpszClassName = "PuntoPyWnd"
    if not user32.RegisterClassW(ctypes.byref(cls)):
        print("RegisterClass failed:", ctypes.get_last_error())
        return 1
    hwnd = user32.CreateWindowExW(0, "PuntoPyWnd", core.APP_NAME, 0, 0, 0, 0, 0,
                                  None, None, hinst, None)

    MAIN_HWND[0] = hwnd
    settings = core.load_settings()
    # ключи запуска включают режимы; без них - как было в прошлый раз
    SW.auto = "--auto" in sys.argv or bool(settings.get("auto"))
    SW.auto_spell = "--spell" in sys.argv or bool(settings.get("spell"))
    SW.apply_settings(settings, DEFAULT_TRIGGER)
    if "--no-double-space" in sys.argv:
        SW.trigger = "off"

    nid.cbSize = ctypes.sizeof(NOTIFYICONDATA)
    nid.hWnd = hwnd
    nid.uID = 1
    nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
    nid.uCallbackMessage = WM_TRAY
    nid.hIcon = load_tray_icon()
    nid.szTip = tray_tip()
    shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))

    hooks = [user32.SetWindowsHookExW(WH_KEYBOARD_LL, keyboard_proc, hinst, 0),
             user32.SetWindowsHookExW(WH_MOUSE_LL, mouse_proc, hinst, 0)]
    if not all(hooks):
        print("Не удалось поставить хук:", ctypes.get_last_error())
        return 1

    for hk_id, mod in ((HK_WORD, 0), (HK_SEL, MOD_SHIFT),
                       (HK_AUTO, MOD_CONTROL), (HK_EXIT, MOD_CONTROL | MOD_SHIFT),
                       (HK_SPELL, MOD_CONTROL | MOD_ALT)):
        if not user32.RegisterHotKey(hwnd, hk_id, mod, VK_PAUSE):
            print("Горячая клавиша занята другой программой, id =", hk_id)

    print("Запущено. Pause - раскладка слова, Shift+Pause - выделенное, "
          "Ctrl+Alt+Pause - орфография слова, Ctrl+Pause - авто-режим, "
          "Ctrl+Shift+Pause - выход.")

    threading.Thread(target=auto_update_loop, daemon=True).start()

    msg = w.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))

    for h in hooks:
        user32.UnhookWindowsHookEx(h)
    shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
    return 0


if __name__ == "__main__":
    sys.exit(main())
