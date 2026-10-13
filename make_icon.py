# -*- coding: utf-8 -*-
"""Рисует tilashar.ico - значок-диафрагму (лепестки объектива) для трея и exe.

    py make_icon.py          (нужен Pillow: py -m pip install pillow)

Каждый размер рисуется отдельно с 8-кратным сглаживанием: уменьшенная
большая картинка на 16 px превращается в кашу.
"""

import math
import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
SS = 8                                   # сглаживание

RING = (28, 52, 92, 255)                 # тёмно-синяя оправа
BLADES = [(70, 140, 220, 255), (52, 116, 196, 255)]   # лепестки двух оттенков
HOLE = (235, 244, 255, 255)              # светлое отверстие
N = 6                                    # число лепестков


def draw(size):
    s = size * SS
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = s / 2
    r_out = s * 0.48
    r_in = s * (0.40 if size >= 32 else 0.38)
    r_hole = s * 0.15

    d.ellipse([c - r_out, c - r_out, c + r_out, c + r_out], fill=RING)
    d.ellipse([c - r_in, c - r_in, c + r_in, c + r_in], fill=HOLE)

    # лепесток: от края шестиугольного отверстия по касательной к оправе
    for i in range(N):
        a0 = 2 * math.pi * i / N + math.pi / 2
        a1 = a0 + 2 * math.pi / N
        h0 = (c + r_hole * math.cos(a0), c - r_hole * math.sin(a0))
        h1 = (c + r_hole * math.cos(a1), c - r_hole * math.sin(a1))
        tip = (c + r_in * 1.35 * math.cos(a0 - 0.35), c - r_in * 1.35 * math.sin(a0 - 0.35))
        tip2 = (c + r_in * 1.35 * math.cos(a1 - 0.35), c - r_in * 1.35 * math.sin(a1 - 0.35))
        d.polygon([h0, h1, tip2, tip], fill=BLADES[i % 2])
        if size >= 24:                   # тонкие швы между лепестками
            d.line([h1, tip2], fill=RING, width=max(1, s // 64))

    # лепестки вылезают за оправу - обрезаем по внутреннему кругу и рисуем её поверх
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).ellipse([c - r_in, c - r_in, c + r_in, c + r_in], fill=255)
    ring = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse([c - r_out, c - r_out, c + r_out, c + r_out], fill=RING)
    ring.paste(img, (0, 0), mask)
    return ring.resize((size, size), Image.LANCZOS)


def main():
    images = [draw(n) for n in SIZES]
    path = os.path.join(HERE, "tilashar.ico")
    images[-1].save(path, sizes=[(n, n) for n in SIZES], append_images=images[:-1])
    images[-1].save(os.path.join(HERE, "tilashar.png"))
    print("готово:", path)


if __name__ == "__main__":
    main()
