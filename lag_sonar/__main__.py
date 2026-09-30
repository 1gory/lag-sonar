"""Точка входа: `python3 -m lag_sonar` поднимает иконку в menu bar.

Для текстовой диагностики без GUI есть `python3 -m lag_sonar.cli`.
"""

from __future__ import annotations

from .app import main

if __name__ == "__main__":
    raise SystemExit(main())
