#!/bin/bash
# Убирает Punto-переключатель из автозапуска и останавливает его.

cd "$(dirname "$0")" || exit 1

echo "Punto-переключатель - удаление из автозапуска"

PLIST="$HOME/Library/LaunchAgents/com.punto.switcher.plist"
if [ -f "$PLIST" ]; then
    launchctl unload "$PLIST" 2>/dev/null
    rm -f "$PLIST"
    printf "   \033[32m%s\033[0m\n" "автозапуск убран"
else
    printf "   \033[33m%s\033[0m\n" "автозапуска не было"
fi

if pkill -f "punto_mac.py" 2>/dev/null; then
    printf "   \033[32m%s\033[0m\n" "программа остановлена"
else
    printf "   \033[33m%s\033[0m\n" "программа не была запущена"
fi

echo
echo "Файлы остались на месте - можно запустить install-mac.command снова."
printf "\nНажмите Enter, чтобы закрыть окно"
read -r _
