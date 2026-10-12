#!/bin/bash
# Поставить LagSonar.app в /Applications и в «Объекты входа».
#
#   ./scripts/install-app.sh              установить, добавить в автозапуск, запустить
#   ./scripts/install-app.sh --uninstall  убрать из автозапуска и удалить
#
# Автозапуск виден и выключается в Системных настройках → Основные → Объекты входа.
# При первом запуске macOS спросит разрешение управлять «System Events» —
# через него добавляется объект входа.

set -euo pipefail

PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NAME="LagSonar"
SOURCE="$PROJECT/dist/$APP_NAME.app"
TARGET="/Applications/$APP_NAME.app"

remove_login_item() {
    osascript -e "tell application \"System Events\" to delete (every login item whose name is \"$APP_NAME\")" \
        >/dev/null 2>&1 || true
}

stop_running() {
    # Запущенное приложение и запуск из исходников (python3 -m lag_sonar)
    # рисуют по значку каждый — двух в menu bar быть не должно.
    pkill -x "$APP_NAME" 2>/dev/null || true
    pkill -f -- "-m lag_sonar$" 2>/dev/null || true
}

if [[ "${1:-}" == "--uninstall" ]]; then
    remove_login_item
    stop_running
    rm -rf "$TARGET"
    echo "удалено: $TARGET и объект входа"
    exit 0
fi

if [[ ! -d "$SOURCE" ]]; then
    echo "ошибка: нет $SOURCE — сначала ./scripts/build-app.sh" >&2
    exit 1
fi

# Прежний способ автозапуска запускал исходники; вместе с объектом входа
# получилось бы два значка.
if [[ -f "$HOME/Library/LaunchAgents/ru.itlab.lag-sonar.plist" ]]; then
    "$PROJECT/scripts/install-agent.sh" --uninstall
fi

stop_running
rm -rf "$TARGET"
cp -R "$SOURCE" "$TARGET"

remove_login_item
osascript -e "tell application \"System Events\" to make login item at end with properties {path:\"$TARGET\", hidden:false}" >/dev/null

open "$TARGET"

echo "установлено: $TARGET"
echo "автозапуск: Системные настройки → Основные → Объекты входа"
echo "журнал: ~/Library/Logs/lag-sonar.log"
echo "удалить: $0 --uninstall"
