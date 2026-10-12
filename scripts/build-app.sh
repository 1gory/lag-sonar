#!/bin/bash
# Собрать автономный dist/LagSonar.app (Python и PyObjC внутри).
#
#   ./scripts/build-app.sh
#
# Сборочное окружение — .venv в корне проекта, создаётся при первом запуске.
# Нужен python3 от python.org (universal2): с ним py2app собирает приложение,
# которое не зависит от установленного Python.

set -euo pipefail

PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT"

if [[ ! -x .venv/bin/python ]]; then
    python3 -m venv .venv
    .venv/bin/pip install --quiet --upgrade pip
fi
.venv/bin/pip install --quiet py2app pyobjc-framework-Cocoa

.venv/bin/python scripts/make_app_icon.py build/LagSonar.icns

rm -rf build/bdist.* dist/LagSonar.app
.venv/bin/python setup.py py2app >build/py2app.log 2>&1 || {
    echo "ошибка: py2app упал, подробности в build/py2app.log" >&2
    exit 1
}

# Ad-hoc подпись: без неё macOS на Apple Silicon не запустит бинарник.
codesign --force --deep --sign - dist/LagSonar.app

echo "собрано: $PROJECT/dist/LagSonar.app ($(du -sh dist/LagSonar.app | cut -f1))"
echo "установить: ./scripts/install-app.sh"
