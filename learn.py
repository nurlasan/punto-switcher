# -*- coding: utf-8 -*-
"""Пополняет личный словарь словами из ваших же текстов.

Берёт слова, которых нет в общих словарях, но которые встречаются в ваших
файлах несколько раз - значит, это ваша рабочая лексика, а не опечатка, - и
дописывает их в dict_user.txt. После этого авто-орфография их не трогает.

    py learn.py                      # сканирует папку проекта
    py learn.py D:\\work C:\\notes     # или указанные папки
"""

import collections
import io
import os
import re
import sys

from layouts import DICT, KNOWN, NEVER, HERE, user_file

WORD_RE = re.compile(r"[А-Яа-яЁё]{3,}|[A-Za-z]{3,}")
EXTS = {".md", ".txt", ".py", ".c", ".h", ".cpp", ".js", ".ts", ".json",
        ".yaml", ".yml", ".ini", ".cfg", ".lua", ".sql", ".sh", ".bat"}
SKIP_DIRS = {".git", "node_modules", "__pycache__", "venv", ".venv", "dist", "build"}
MIN_COUNT = 3          # сколько раз слово должно встретиться
MIN_FILES = 2          # и в скольких разных файлах
VOWELS = set("аеёиоуыэюяaeiouy")
HEX_ONLY = set("abcdef0123456789")
MAX_FILE = 2_000_000   # не читаем файлы крупнее


def looks_like_word(word):
    """Отсеивает мусор из кода: hex, base64, идентификаторы без гласных."""
    if not (4 <= len(word) <= 20):
        return False
    if not any(ch in VOWELS for ch in word):
        return False
    if set(word) <= HEX_ONLY:
        return False
    return True


def scan(roots):
    counter = collections.Counter()
    in_files = collections.Counter()
    files = 0
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for name in filenames:
                if os.path.splitext(name)[1].lower() not in EXTS:
                    continue
                path = os.path.join(dirpath, name)
                try:
                    if os.path.getsize(path) > MAX_FILE:
                        continue
                    text = io.open(path, encoding="utf-8", errors="ignore").read()
                except OSError:
                    continue
                files += 1
                words = [w.lower() for w in WORD_RE.findall(text)]
                counter.update(words)
                in_files.update(set(words))
    return counter, in_files, files


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    all_langs = "--all" in argv        # без ключа учим только русские слова:
    roots = args or [os.path.dirname(HERE)]   # латиница в коде - сплошной мусор
    counter, in_files, files = scan(roots)
    fresh = set()
    for word, count in counter.items():
        if count < MIN_COUNT or in_files[word] < MIN_FILES or word in NEVER:
            continue
        if not looks_like_word(word):
            continue
        lang = "ru" if word[0].lower() in "абвгдеёжзийклмнопрстуфхцчшщъыьэюя" else "en"
        if lang == "en" and not all_langs:
            continue
        if word in DICT[lang] or word in KNOWN[lang]:
            continue
        fresh.add(word)

    path = user_file("dict_user.txt")
    existing = [line.rstrip("\n") for line in io.open(path, encoding="utf-8")] if os.path.exists(path) else []
    with io.open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(existing + sorted(fresh)) + "\n")

    print(f"просмотрено файлов: {files}")
    print(f"добавлено слов в dict_user.txt: {len(fresh)}")
    print("примеры:", ", ".join(sorted(fresh)[:20]))


if __name__ == "__main__":
    main(sys.argv)
