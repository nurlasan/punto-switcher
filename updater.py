# -*- coding: utf-8 -*-
"""Обновление exe через GitHub Releases.

Выпуск - это релиз с тегом v1.2.3 и файлом Tilashar.exe (его собирает
.github/workflows/release.yml). Программа сравнивает тег со своей версией,
скачивает exe рядом с собой, проверяет размер и SHA-256 и после выхода
подменяет себя новым файлом.

Работающий exe перезаписать нельзя, поэтому подмену делает отдельный
скрытый PowerShell: ждёт, пока файл освободится, переносит новый на место
старого и запускает его.
"""

import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request

from version import VERSION

REPO = "nurlasan/punto-switcher"
ASSET = "Tilashar.exe"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
TIMEOUT = 20


def frozen():
    """True, если запущены как exe - только тогда есть что обновлять."""
    return bool(getattr(sys, "frozen", False))


def parse_version(text):
    """'v1.2.3' -> (1, 2, 3); мусор -> ()."""
    nums = re.findall(r"\d+", text or "")
    return tuple(int(n) for n in nums[:3])


def _get(url, accept="application/vnd.github+json"):
    req = urllib.request.Request(url, headers={
        "Accept": accept, "User-Agent": f"Tilashar/{VERSION}"})
    return urllib.request.urlopen(req, timeout=TIMEOUT)


def check():
    """Свежий релиз, если он новее нашей версии, иначе None.

    Возвращает {"version", "url", "size", "sha256"}. Ошибки сети - исключение.
    """
    with _get(API) as resp:
        data = json.load(resp)
    tag = data.get("tag_name", "")
    if parse_version(tag) <= parse_version(VERSION):
        return None
    for asset in data.get("assets", []):
        if asset.get("name") == ASSET:
            digest = asset.get("digest") or ""
            return {"version": tag.lstrip("v"),
                    "url": asset["browser_download_url"],
                    "size": asset.get("size", 0),
                    "sha256": digest.split(":", 1)[1] if digest.startswith("sha256:") else ""}
    return None


def download(info):
    """Скачивает новый exe рядом с текущим; возвращает путь к нему."""
    target = sys.executable + ".new"
    part = target + ".part"
    sha = hashlib.sha256()
    size = 0
    with _get(info["url"], accept="application/octet-stream") as resp, open(part, "wb") as f:
        while True:
            chunk = resp.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)
            sha.update(chunk)
            size += len(chunk)
    if info["size"] and size != info["size"]:
        os.remove(part)
        raise IOError(f"скачано {size} байт вместо {info['size']}")
    if info["sha256"] and sha.hexdigest() != info["sha256"].lower():
        os.remove(part)
        raise IOError("контрольная сумма не совпала")
    os.replace(part, target)
    return target


def _ps_quote(path):
    return "'" + path.replace("'", "''") + "'"


def install_and_restart(new_path):
    """Запускает фоновую подмену exe; вызывающий должен сразу завершиться."""
    exe = sys.executable
    script = (
        f"$exe = {_ps_quote(exe)}; $new = {_ps_quote(new_path)}\n"
        "for ($i = 0; $i -lt 60; $i++) {\n"
        "  try { Move-Item -LiteralPath $new -Destination $exe -Force -ErrorAction Stop;"
        " Start-Process -FilePath $exe; exit 0 }\n"
        "  catch { Start-Sleep -Milliseconds 500 }\n"
        "}\n")
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    subprocess.Popen(
        ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
         "-EncodedCommand", encoded],
        creationflags=0x08000000,   # CREATE_NO_WINDOW: процесс переживёт наш выход
        close_fds=True)


def cleanup():
    """Убирает недокачанные файлы прошлых попыток."""
    if not frozen():
        return
    for suffix in (".new", ".new.part"):
        try:
            os.remove(sys.executable + suffix)
        except OSError:
            pass
