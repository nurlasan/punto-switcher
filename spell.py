# -*- coding: utf-8 -*-
"""Исправление опечаток по частотному словарю.

Кандидаты - слова словаря на расстоянии одной правки (вставка, удаление,
замена, перестановка соседних букв). Из них берётся самое частотное.
Правило намеренно строгое: неизвестное слово исправляется, только если
замена заметно частотнее всего остального и само слово не похоже на термин.
"""

import io
import re

from layouts import CYRILLIC, LATIN, DICT, KNOWN, RANK, NEVER, NEVER_STEMS, user_file

RU_ALPHABET = "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"
EN_ALPHABET = "abcdefghijklmnopqrstuvwxyz"

# кандидат должен быть заметно употребимее этого ранга, иначе не трогаем
MAX_RANK = 15000
VOWELS = set("аеёиоуыэюя") | set("aeiouy")
# парные по звонкости согласные; в авто-режим не входят - на них ломается
# жаргон (бейдж->пейдж, деплою->теплою, блокер->блогер)
PAIRS = {frozenset(p) for p in ("бп", "вф", "гк", "дт", "жш", "зс")}

# В авто-режиме исправляются только правки, характерные для опечаток:
# перепутанная гласная, пропущенная или лишняя гласная, перестановка соседних
# букв, удвоение, мягкий знак, парная согласная. Замены согласных не трогаем -
# именно на них ломается жаргон (батч->матч, креды->среды, флоу->флот).
AUTO_KINDS = {"vowel", "vowel_indel", "transpose", "double", "soft"}
AUTO_MIN_LEN = 5      # короткие слова слишком часто оказываются жаргоном
MIN_LEN = 4
MAX_LEN = 16

_HAS_DIGIT = re.compile(r"\d")


def _load_replacements():
    """Таблица автозамен из replace.txt: {что: на что}."""
    out = {}
    path = user_file("replace.txt")
    try:
        for line in io.open(path, encoding="utf-8"):
            line = line.split("#")[0].strip()
            if "=" in line:
                bad, good = line.split("=", 1)
                if bad.strip():
                    out[bad.strip().lower()] = good.strip()
    except OSError:
        pass
    return out


REPLACE = _load_replacements()


def _edits1(word, alphabet):
    splits = [(word[:i], word[i:]) for i in range(len(word) + 1)]
    out = set()
    for left, right in splits:
        if right:
            out.add(left + right[1:])                      # удаление
            if len(right) > 1:
                out.add(left + right[1] + right[0] + right[2:])   # перестановка
            for ch in alphabet:
                out.add(left + ch + right[1:])             # замена
        for ch in alphabet:
            out.add(left + ch + right)                     # вставка
    out.discard(word)
    return out


def edit_kind(bad, good):
    """Тип единственной правки между словами: 'vowel', 'transpose' и т.п."""
    if len(bad) == len(good):
        diff = [i for i, (a, b) in enumerate(zip(bad, good)) if a != b]
        if len(diff) == 1:
            a, b = bad[diff[0]], good[diff[0]]
            if a in VOWELS and b in VOWELS:
                return "vowel"
            if {a, b} & set("ьъ"):
                return "soft"
            if frozenset((a, b)) in PAIRS:
                return "pair"
            return "consonant"
        if (len(diff) == 2 and diff[1] == diff[0] + 1
                and bad[diff[0]] == good[diff[1]] and bad[diff[1]] == good[diff[0]]):
            return "transpose"
        return "other"

    long, short = (bad, good) if len(bad) > len(good) else (good, bad)
    for i, ch in enumerate(long):
        if long[:i] + long[i + 1:] == short:
            if ch in "ьъ":
                return "soft"
            if long[i - 1:i] == ch or long[i + 1:i + 2] == ch:
                return "double"
            return "vowel_indel" if ch in VOWELS else "consonant_indel"
    return "other"


def lang_of(word):
    ru = sum(1 for ch in word if ch in CYRILLIC)
    en = sum(1 for ch in word if ch in LATIN)
    if ru and not en:
        return "ru"
    if en and not ru:
        return "en"
    return None


def skip(word):
    """Слова, которые не проверяем: термины, имена, сокращения, кодовые."""
    letters = [ch for ch in word if ch.isalpha()]
    if not (MIN_LEN <= len(letters) <= MAX_LEN):
        return True
    if _HAS_DIGIT.search(word) or "_" in word:
        return True
    core = "".join(letters)
    if core.upper() == core:                  # АББРЕВИАТУРА
        return True
    if any(ch.isupper() for ch in core[1:]):  # camelCase, СмешанныйРегистр
        return True
    low = core.lower()
    if low in NEVER:
        return True
    # однокоренные словам из стоп-листа: баг -> багов, деплой -> деплою
    return any(low.startswith(stem) for stem in NEVER_STEMS)


def suggest(word, strict=False):
    """Лучшее исправление слова или None, если менять не надо.

    strict=True (авто-режим) дополнительно требует, чтобы исправление было
    заметно правдоподобнее исходного слова.
    """
    lang = lang_of(word)
    if lang is None:
        return None
    bare = "".join(ch for ch in word if ch.isalpha()).lower()
    if bare in REPLACE:
        return _match_case("".join(ch for ch in word if ch.isalpha()), REPLACE[bare])
    if skip(word):
        return None
    core = "".join(ch for ch in word if ch.isalpha())
    low = core.lower()
    if low in REPLACE:                        # прямая автозамена
        return _match_case(core, REPLACE[low])
    if low in DICT[lang] or low in KNOWN[lang]:   # слово известно - не трогаем
        return None

    alphabet = RU_ALPHABET if lang == "ru" else EN_ALPHABET
    ranks = RANK[lang]
    best, best_rank = None, MAX_RANK + 1
    rare = []                                  # кандидаты вне частотного списка
    for cand in _edits1(low, alphabet):
        r = ranks.get(cand)
        if r is not None:
            if r < best_rank:
                best, best_rank = cand, r
        elif cand in KNOWN[lang]:
            rare.append(cand)
    if best is None:
        # частотных вариантов нет; редкий годится, только если он единственный -
        # тогда выбор однозначен и гадать не приходится
        if len(rare) != 1:
            return None
        best = rare[0]
    if strict and (len(low) < AUTO_MIN_LEN or edit_kind(low, best) not in AUTO_KINDS):
        return None
    if strict and lang == "en" and not _en_auto_ok(core, low, best, ranks):
        return None
    return _match_case(core, best)


def _en_auto_ok(core, low, best, ranks):
    """Доп. фильтр авто-режима для английского: там полно терминов и имён.

    Правка должна быть внутри слова: опечатки почти не задевают первую букву,
    а на краях живут термины (stdio->studio, endian->indian, clientid->cliented).
    """
    if core[:1].isupper():                     # Marvell, Nagle - имена
        return False
    if best not in ranks:                      # minmax->minimax, callgraph->calligraph
        return False
    pre = 0
    while pre < min(len(low), len(best)) and low[pre] == best[pre]:
        pre += 1
    suf = 0
    while (suf < min(len(low), len(best)) - pre
           and low[-1 - suf] == best[-1 - suf]):
        suf += 1
    if pre < 1:
        return False
    if pre < 2 and edit_kind(low, best) == "double":   # sstream, fflush, ccomplex
        return False
    # перестановка в конце - частая опечатка (lenght, macth); прочее - нет
    return suf >= 2 or edit_kind(low, best) == "transpose"


def _match_case(src, dst):
    """Переносит регистр исходного слова на исправленное."""
    if src.isupper():
        return dst.upper()
    if src[:1].isupper():
        return dst[:1].upper() + dst[1:]
    return dst


def correct(word, strict=False):
    """Исправляет слово, сохраняя знаки препинания по краям."""
    left = len(word) - len(word.lstrip("«\"'([{"))
    right = len(word) - len(word.rstrip("»\"'.,!?:;)]}"))
    core = word[left:len(word) - right] if right else word[left:]
    fixed = suggest(core, strict)
    if not fixed:
        return None
    return word[:left] + fixed + (word[len(word) - right:] if right else "")
