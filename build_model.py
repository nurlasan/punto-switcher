# -*- coding: utf-8 -*-
"""Строит словари и триграммную модель из частотных списков.

Вход:  ru_50k.txt / en_50k.txt (строки вида "слово частота", FrequencyWords)
Выход: dict_ru.txt, dict_en.txt  - слова, по одному в строке
       model.json                - лог-вероятности триграмм для обоих языков

Запускать один раз; результат коммитится рядом со скриптом.
"""

import json
import math
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
RU_RE = re.compile(r"^[а-яё]{1,}$")
EN_RE = re.compile(r"^[a-z]{1,}$")


def read_freq(name, pattern):
    words = []
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        for line in f:
            parts = line.split()
            if len(parts) != 2:
                continue
            word, cnt = parts[0].lower(), int(parts[1])
            if pattern.match(word):
                words.append((word, cnt))
    return words


def trigram_model(words):
    """Лог-вероятности P(c3 | c1c2) с аддитивным сглаживанием."""
    ctx, tri = {}, {}
    for word, cnt in words:
        s = "^" + word + "$"
        for i in range(len(s) - 2):
            a, b, c = s[i], s[i + 1], s[i + 2]
            ctx[a + b] = ctx.get(a + b, 0) + cnt
            tri[a + b + c] = tri.get(a + b + c, 0) + cnt
    alphabet = len({ch for word, _ in words for ch in word}) + 2
    model = {}
    for key, n in tri.items():
        model[key] = round(math.log((n + 1) / (ctx[key[:2]] + alphabet)), 3)
    # запасная величина для триграмм, которых в модели нет
    floor = round(math.log(1 / (sum(ctx.values()) / max(len(ctx), 1) + alphabet)), 3)
    return model, floor


def main():
    out = {}
    for lang, name, pattern in (("ru", "ru_50k.txt", RU_RE), ("en", "en_50k.txt", EN_RE)):
        words = read_freq(name, pattern)
        with open(os.path.join(HERE, f"dict_{lang}.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(word for word, _ in words))
        model, floor = trigram_model(words)
        out[lang] = {"floor": floor, "tri": model}
        print(f"{lang}: слов {len(words)}, триграмм {len(model)}, floor {floor}")

    with open(os.path.join(HERE, "model.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    size = os.path.getsize(os.path.join(HERE, "model.json")) / 1024
    print(f"model.json: {size:.0f} КБ")


if __name__ == "__main__":
    main()
