# -*- coding: utf-8 -*-
"""Таблицы раскладок ЙЦУКЕН <-> QWERTY и определение «набрано не в той раскладке».

Решение принимается по словарям (dict_ru.txt / dict_en.txt) и триграммной
модели (model.json) - оба файла делает build_model.py из частотных списков.
Без этих файлов остаётся грубая запасная эвристика.
"""

import json
import math
import os

from wordset import WordSet

RU_LCID = 0x0419
EN_LCID = 0x0409

_RU = ("йцукенгшщзхъфывапролджэячсмитьбю.ё"
       "ЙЦУКЕНГШЩЗХЪФЫВАПРОЛДЖЭЯЧСМИТЬБЮ,Ё"
       "№")
_EN = ("qwertyuiop[]asdfghjkl;'zxcvbnm,./`"
       "QWERTYUIOP{}ASDFGHJKL:\"ZXCVBNM<>?~"
       "#")

assert len(_RU) == len(_EN), (len(_RU), len(_EN))

RU2EN = {r: e for r, e in zip(_RU, _EN)}
EN2RU = {e: r for r, e in zip(_RU, _EN)}

CYRILLIC = set("абвгдеёжзийклмнопрстуфхцчшщъыьэюяАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ")
LATIN = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")

HERE = os.path.dirname(os.path.abspath(__file__))


def detect_direction(text):
    """'ru2en', если текст в основном кириллический, иначе 'en2ru'."""
    ru = sum(1 for ch in text if ch in CYRILLIC)
    en = sum(1 for ch in text if ch in LATIN)
    return "ru2en" if ru >= en else "en2ru"


def convert(text):
    """Переводит текст в другую раскладку посимвольно."""
    table = RU2EN if detect_direction(text) == "ru2en" else EN2RU
    return "".join(table.get(ch, ch) for ch in text)


# ------------------------------------------------------------ модель языка

def _load_dict(name):
    try:
        with open(os.path.join(HERE, name), encoding="utf-8") as f:
            return {line.strip() for line in f if line.strip()}
    except OSError:
        return set()


def _load_ranked(name):
    """{слово: порядковый номер}; файлы отсортированы по убыванию частоты."""
    try:
        with open(os.path.join(HERE, name), encoding="utf-8") as f:
            return {line.strip(): i for i, line in enumerate(f) if line.strip()}
    except OSError:
        return {}


def _load_model():
    try:
        with open(os.path.join(HERE, "model.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


RANK = {"ru": _load_ranked("dict_ru.txt"), "en": _load_ranked("dict_en.txt")}
DICT = {lang: set(ranks) for lang, ranks in RANK.items()}
# слова, которые никогда не трогать (свои термины, имена, аббревиатуры)
NEVER = {word.lower() for word in _load_dict("dict_user.txt")}
# корни стоп-слов: от них отсекаются и словоформы (баг -> багов, деплой -> деплою)
NEVER_STEMS = {word for word in NEVER if len(word) >= 4}
# большие словари словоформ (на диске, ищутся бинарным поиском)
KNOWN = {"ru": WordSet(os.path.join(HERE, "words_ru.txt")),
         "en": WordSet(os.path.join(HERE, "words_en.txt"))}

MODEL = _load_model()
HAVE_MODEL = bool(MODEL.get("ru") and MODEL.get("en"))


def logprob(word, lang):
    """Средний лог P(символ | два предыдущих) - насколько слово похоже на язык."""
    m = MODEL[lang]
    tri, floor = m["tri"], m["floor"]
    s = "^" + word.lower() + "$"
    total = sum(tri.get(s[i:i + 3], floor) for i in range(len(s) - 2))
    return total / (len(s) - 2)


_RU_VOWELS = set("аеёиоуыэюя")
_EN_VOWELS = set("aeiouy")

# минимальный перевес в пользу другой раскладки (нат на символ)
THRESHOLD = 1.5

# русское слово не начинается с этих букв
_RU_BAD_START = set("ьъы")


def _impossible(word, lang):
    """Слово, невозможное в этом языке: без гласных или с неверным началом."""
    letters = [ch.lower() for ch in word if ch.isalpha()]
    if not letters:
        return True
    if not any(ch in (_RU_VOWELS if lang == "ru" else _EN_VOWELS) for ch in letters):
        return True
    return lang == "ru" and letters[0] in _RU_BAD_START


def looks_wrong(word):
    """True, если слово скорее набрано в неправильной раскладке.

    Сначала словари (точный ответ), затем триграммная модель. При сомнении
    возвращаем False - лучше не трогать текст, чем испортить.
    """
    letters = [ch for ch in word if ch.isalpha()]
    if len(letters) < 2:
        return False
    ru = sum(1 for ch in letters if ch in CYRILLIC)
    en = sum(1 for ch in letters if ch in LATIN)
    if ru and en:                      # смешанное слово - не трогаем
        return False

    other = convert(word)
    cur_lang, alt_lang = ("ru", "en") if ru else ("en", "ru")
    lw = "".join(letters).lower()
    lo = "".join(ch for ch in other if ch.isalpha()).lower()

    if lw in NEVER:
        return False

    # частотный словарь: другая раскладка даёт частое слово, а эта - нет
    if lo in DICT[alt_lang] and lw not in DICT[cur_lang]:
        return True
    # слово известно в своём языке - не трогаем
    if lw in DICT[cur_lang] or lw in KNOWN[cur_lang]:
        return False
    # слово неизвестно, а его конвертация - нормальное слово другого языка
    if lo and lo in KNOWN[alt_lang]:
        return True

    if not HAVE_MODEL:
        return _fallback(word, other, cur_lang)

    # символы, которых в целевом алфавите нет (»[«, »;«), - признак, что
    # текущий вариант правильный
    alien = sum(1 for ch in other if ch.isprintable() and not ch.isspace()
                and ch not in (CYRILLIC if alt_lang == "ru" else LATIN))
    if alien or _impossible(other, alt_lang):
        return False

    return logprob(lo, alt_lang) - logprob(lw, cur_lang) >= THRESHOLD


def _fallback(word, other, cur_lang):
    """Запасной вариант без модели: слово без гласных почти наверняка неверное."""
    letters = [ch.lower() for ch in word if ch.isalpha()]
    vowels = _RU_VOWELS if cur_lang == "ru" else _EN_VOWELS
    other_vowels = _EN_VOWELS if cur_lang == "ru" else _RU_VOWELS
    if len(letters) < 4 or any(ch in vowels for ch in letters):
        return False
    return any(ch.lower() in other_vowels for ch in other if ch.isalpha())
