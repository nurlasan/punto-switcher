#!/bin/bash
# Установка Punto-переключателя на macOS.
# Двойной клик в Finder. Если Finder отказывается запускать, выполните один раз:
#   chmod +x install-mac.command

cd "$(dirname "$0")" || exit 1
HERE="$(pwd)"

step() { printf "\n>> %s\n" "$1"; }
ok()   { printf "   %s\n" "$1"; }
bad()  { printf "   [!] %s\n" "$1"; }
hold() { printf "\nНажмите Enter, чтобы закрыть окно"; read -r _; }

echo "Punto-переключатель - установка на macOS"

# --- 1. Python -------------------------------------------------------------
step "Проверяю Python 3"
PY=""
for cand in python3 /usr/bin/python3 /opt/homebrew/bin/python3 /usr/local/bin/python3; do
    if command -v "$cand" >/dev/null 2>&1; then PY="$(command -v "$cand")"; break; fi
done
if [ -z "$PY" ]; then
    bad "Python 3 не найден."
    echo "   Установите его: откройте Терминал и выполните  xcode-select --install"
    echo "   или скачайте с https://www.python.org/downloads/"
    hold; exit 1
fi
ok "нашёл: $PY ($("$PY" --version 2>&1))"

# --- 2. Зависимости --------------------------------------------------------
step "Ставлю pyobjc (нужен для перехвата клавиш)"
if "$PY" -c "import Quartz, AppKit" >/dev/null 2>&1; then
    ok "уже установлен"
else
    installed=0
    # у свежих сборок python установка без отдельного флага запрещена
    for flags in "--user" "--user --break-system-packages" "--break-system-packages"; do
        # shellcheck disable=SC2086
        if "$PY" -m pip install $flags -r requirements-mac.txt >>/tmp/punto-pip.log 2>&1; then
            installed=1; break
        fi
    done
    if [ "$installed" = "1" ]; then
        ok "установлен"
    else
        bad "не получилось установить, подробности в /tmp/punto-pip.log"
        echo "   Вручную:  $PY -m pip install --user pyobjc-framework-Cocoa pyobjc-framework-Quartz"
        hold; exit 1
    fi
fi

# --- 3. Проверка логики ----------------------------------------------------
step "Проверяю словари и логику"
if "$PY" tests.py >/tmp/punto-tests.log 2>&1; then
    ok "тесты пройдены"
else
    bad "тесты не прошли, смотрите /tmp/punto-tests.log"
    tail -5 /tmp/punto-tests.log
    hold; exit 1
fi

# --- 4. Права на перехват клавиш -------------------------------------------
step "Проверяю доступ к клавиатуре"
if "$PY" punto_mac.py --check >/tmp/punto-check.log 2>&1; then
    ok "доступ есть, обе раскладки найдены"
else
    cat /tmp/punto-check.log
    bad "нет доступа к клавиатуре или не найдены раскладки"
    echo "   Сейчас откроются Системные настройки -> Универсальный доступ."
    echo "   Включите там Терминал (или ваш python3) и запустите меня снова."
    open "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
    hold; exit 1
fi

# --- 5. Прежняя копия ------------------------------------------------------
step "Останавливаю прежнюю копию, если запущена"
if pkill -f "punto_mac.py" 2>/dev/null; then ok "остановлена"; else ok "не была запущена"; fi
launchctl unload "$HOME/Library/LaunchAgents/com.punto.switcher.plist" 2>/dev/null

# --- 6. Автозапуск ---------------------------------------------------------
step "Настраиваю автозапуск"
mkdir -p "$HOME/Library/LaunchAgents"
PLIST="$HOME/Library/LaunchAgents/com.punto.switcher.plist"
cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.punto.switcher</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PY</string>
    <string>$HERE/punto_mac.py</string>
    <string>--auto</string>
    <string>--spell</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$HERE</string>
  <key>RunAtLoad</key>
  <true/>
  <key>StandardErrorPath</key>
  <string>/tmp/punto-switcher.log</string>
  <key>StandardOutPath</key>
  <string>/tmp/punto-switcher.log</string>
</dict>
</plist>
PLISTEOF
ok "$PLIST"

# --- 7. Запуск -------------------------------------------------------------
step "Запускаю"
launchctl load "$PLIST" 2>/dev/null
sleep 3
if pgrep -f "punto_mac.py" >/dev/null; then
    ok "работает"
else
    bad "не запустилась, смотрите /tmp/punto-switcher.log"
    tail -10 /tmp/punto-switcher.log 2>/dev/null
    hold; exit 1
fi

cat <<'HELP'

Готово. Значок появился в строке меню справа вверху.

   двойной Shift     - перевести последнее слово в другую раскладку
   Ctrl+Opt+Shift+L  - перевести выделенный текст
   Ctrl+Opt+S        - исправить опечатку в слове
   Ctrl+Opt+A        - включить/выключить авто-раскладку
   Ctrl+Opt+P        - включить/выключить авто-орфографию
   Ctrl+Opt+Q        - выход

   Авто-раскладка и авто-орфография уже включены.
   Убрать из автозапуска: двойной клик по uninstall-mac.command
HELP
hold
