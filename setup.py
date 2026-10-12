"""Сборка LagSonar.app через py2app. Запускать не напрямую, а через
`./scripts/build-app.sh` — он готовит окружение и иконку."""

import re
from pathlib import Path

from setuptools import setup

VERSION = re.search(
    r'__version__ = "([^"]+)"', Path("lag_sonar/__init__.py").read_text()
).group(1)

setup(
    name="LagSonar",
    app=["scripts/app_entry.py"],
    options={
        "py2app": {
            "packages": ["lag_sonar"],
            "iconfile": "build/LagSonar.icns",
            "plist": {
                "CFBundleName": "LagSonar",
                "CFBundleDisplayName": "LagSonar",
                "CFBundleIdentifier": "ru.itlab.lag-sonar",
                "CFBundleShortVersionString": VERSION,
                "CFBundleVersion": VERSION,
                # Только значок в menu bar: без иконки в Dock и без главного окна.
                "LSUIElement": True,
                "LSMinimumSystemVersion": "12.0",
                # Без этого описания macOS молча запрещает ходить в локальную
                # сеть, и проба роутера всегда отвечает «хост недостижим».
                "NSLocalNetworkUsageDescription": (
                    "LagSonar проверяет, отвечает ли роутер, чтобы отличить "
                    "поломку домашней сети от проблем провайдера."
                ),
                "NSHumanReadableCopyright": "itlabrealty",
            },
        }
    },
)
