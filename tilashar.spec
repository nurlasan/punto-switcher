# -*- mode: python ; coding: utf-8 -*-
# Сборка Tilashar.exe: py -m PyInstaller --noconfirm tilashar.spec  (или build-exe.bat)
# Один файл, без консоли. Словари едут внутри exe; личные файлы (dict_user.txt,
# replace.txt, settings.json) при первом запуске копируются в %APPDATA%\Tilashar.

DATA = ["dict_ru.txt", "dict_en.txt", "model.json", "words_ru.txt", "words_en.txt",
        "dict_user.txt", "replace.txt", "tilashar.ico"]

a = Analysis(
    ["punto.py"],
    datas=[(name, ".") for name in DATA],
    excludes=["tkinter", "unittest", "pydoc", "AppKit", "Quartz", "objc"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name="Tilashar",
    console=False,
    upx=False,
    icon="tilashar.ico",
)
