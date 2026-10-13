# -*- coding: utf-8 -*-
"""Таблицы раскладок ЙЦУКЕН <-> QWERTY и определение «набрано не в той раскладке».

Решение принимается по словарям (dict_ru.txt / dict_en.txt) и триграммной
модели (model.json) - оба файла делает build_model.py из частотных списков.
Без этих файлов остаётся грубая запасная эвристика.
"""

import json
import math
import os
import shutil
import sys

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

APP_NAME = "Tilashar"

# HERE - словари и модель (только чтение); USER_DIR - то, что человек правит
# сам и что должно пережить обновление: dict_user.txt, replace.txt, settings.json.
# В exe (PyInstaller) словари лежат во временной папке распаковки, поэтому
# личные файлы живут в %APPDATA%\Tilashar; при запуске скриптом - рядом с ними.
if getattr(sys, "frozen", False):
    HERE = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    USER_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), APP_NAME)
else:
    HERE = USER_DIR = os.path.dirname(os.path.abspath(__file__))


def user_file(name):
    """Путь к личному файлу; при первом запуске exe копирует туда исходный."""
    path = os.path.join(USER_DIR, name)
    if not os.path.exists(path) and USER_DIR != HERE:
        try:
            os.makedirs(USER_DIR, exist_ok=True)
            shutil.copyfile(os.path.join(HERE, name), path)
        except OSError:
            pass
    return path


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

def _load_dict(path):
    try:
        with open(path, encoding="utf-8") as f:
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
NEVER = {word.lower() for word in _load_dict(user_file("dict_user.txt"))}
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


# Короткие служебные слова: предлоги, союзы, местоимения. Словарю и модели
# на 1-2 буквах верить нельзя, поэтому решаем по явным спискам.
SHORT = {
    "ru": {"в", "к", "с", "у", "о", "а", "и", "я",
           "не", "на", "но", "за", "по", "до", "из", "от", "об", "во", "ко",
           "со", "он", "мы", "ты", "вы", "их", "её", "ее", "ей", "им", "ли",
           "же", "бы", "да", "ну", "то", "уж", "ни", "ой"},
    "en": {"a", "i", "in", "to", "is", "on", "at", "of", "it", "my", "we",
           "he", "me", "be", "do", "go", "so", "no", "up", "us", "or", "an",
           "as", "by", "if", "am", "ok"},
}
# короткие слова, которые в другом языке сами что-то значат
# (vs, kb, ns - термины; ща, гы - сленг); их меняем только по соседям
SHORT_AMBIGUOUS = {"vs", "kb", "ns", "ds", "lf", "tt", "ye", "bv", "nj", "cj",
                   "rj", "pf", "jq", "dj", "bp", "yt", "lj",
                   "ща", "гы", "ин", "фе"}


def short_wrong(word, context=False):
    """True, если короткое слово (1-2 символа) набрано не в той раскладке.

    context=True - предыдущее слово набрано на другом языке, это повод
    поменять и неоднозначные слова (одиночные буквы, vs, kb).
    """
    if not word or len(word) > 2:
        return False
    low = word.lower()
    if low in NEVER or (len(word) == 2 and word.isupper()):   # PF, BP - аббревиатуры
        return False
    other = convert(word).lower()
    alt, cur = ("en", "ru") if detect_direction(word) == "ru2en" else ("ru", "en")
    if other not in SHORT[alt] or low in SHORT[cur]:
        return False
    # одиночные латинские буквы (c, b, e) бывают пунктами и переменными;
    # одиночные «ш», «ф» по-русски не значат ничего
    if low in SHORT_AMBIGUOUS or (len(word) == 1 and cur == "en"):
        return context
    return True


def _fallback(word, other, cur_lang):
    """Запасной вариант без модели: слово без гласных почти наверняка неверное."""
    letters = [ch.lower() for ch in word if ch.isalpha()]
    vowels = _RU_VOWELS if cur_lang == "ru" else _EN_VOWELS
    other_vowels = _EN_VOWELS if cur_lang == "ru" else _RU_VOWELS
    if len(letters) < 4 or any(ch in vowels for ch in letters):
        return False
    return any(ch.lower() in other_vowels for ch in other if ch.isalpha())
