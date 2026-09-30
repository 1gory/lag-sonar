#!/bin/bash
# Поставить lag-sonar в автозапуск при входе в систему.
#
#   ./scripts/install-agent.sh            установить и запустить
#   ./scripts/install-agent.sh --uninstall  выключить и убрать
#
# Ставится в пользовательские LaunchAgents, права администратора не нужны.

set -euo pipefail

LABEL="ru.itlab.lag-sonar"
PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMPLATE="$PROJECT/scripts/$LABEL.plist"
TARGET="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"

uninstall() {
    if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
        launchctl bootout "$DOMAIN/$LABEL"
        echo "выгружен: $LABEL"
    else
        echo "не был загружен: $LABEL"
    fi
    rm -f "$TARGET"
    echo "удалён: $TARGET"
}

if [[ "${1:-}" == "--uninstall" ]]; then
    uninstall
    exit 0
fi

PYTHON="$(command -v python3)"
if ! "$PYTHON" -c "import AppKit" >/dev/null 2>&1; then
    echo "ошибка: у $PYTHON нет PyObjC (модуль AppKit)." >&2
    echo "укажите другой интерпретатор: PATH=/путь/к/bin:\$PATH $0" >&2
    exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents"
sed -e "s|__PYTHON__|$PYTHON|g" \
    -e "s|__PROJECT__|$PROJECT|g" \
    -e "s|__HOME__|$HOME|g" \
    "$TEMPLATE" > "$TARGET"

# Перед загрузкой снимаем прежнюю версию, иначе launchctl ругнётся на дубликат.
launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
launchctl bootstrap "$DOMAIN" "$TARGET"
launchctl kickstart -k "$DOMAIN/$LABEL"

echo "установлен: $TARGET"
echo "интерпретатор: $PYTHON"
echo "значок должен появиться в menu bar в течение нескольких секунд."
echo "журнал: ~/Library/Logs/lag-sonar.log"
echo "выключить: $0 --uninstall"
