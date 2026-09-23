# -*- coding: utf-8 -*-
"""Большой словарь словоформ на диске: бинарный поиск по mmap.

Полтора миллиона слов в памяти держать незачем - файл отсортирован побайтово,
проверка слова стоит десяток обращений к странице файла.
"""

import mmap
import os


class WordSet:
    """Отсортированный список слов в файле; поддерживает `word in wordset`."""

    def __init__(self, path):
        self.path = path
        self._fh = None
        self._mm = None
        if os.path.exists(path) and os.path.getsize(path) > 0:
            self._fh = open(path, "rb")
            self._mm = mmap.mmap(self._fh.fileno(), 0, access=mmap.ACCESS_READ)

    def __bool__(self):
        return self._mm is not None

    def close(self):
        if self._mm:
            self._mm.close()
            self._mm = None
        if self._fh:
            self._fh.close()
            self._fh = None

    def _line_at(self, pos):
        """Строка, содержащая байт pos, и позиция её начала."""
        mm = self._mm
        start = mm.rfind(b"\n", 0, pos) + 1
        end = mm.find(b"\n", start)
        if end < 0:
            end = len(mm)
        return mm[start:end], start

    def __contains__(self, word):
        if not self._mm:
            return False
        target = word.encode("utf-8")
        lo, hi = 0, len(self._mm)
        while lo < hi:
            mid = (lo + hi) // 2
            line, start = self._line_at(mid)
            if line == target:
                return True
            if line < target:
                # следующая строка после найденной
                nxt = start + len(line) + 1
                if nxt >= hi:
                    return False
                lo = nxt
            else:
                if start <= lo:
                    return False
                hi = start
        return False
