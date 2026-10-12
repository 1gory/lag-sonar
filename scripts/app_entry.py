"""Точка входа для py2app: ему нужен файл-скрипт, а не `-m lag_sonar`."""

from lag_sonar.app import main

raise SystemExit(main())
