"""Выпадающее меню: расклад по слоям и действия.

Меню — единственное место, где состояние объясняется словами, поэтому строки
должны читаться как ответ на вопрос «что именно сломалось», а не как дамп проб.
"""

from __future__ import annotations

from AppKit import (
    NSAttributedString,
    NSFont,
    NSFontAttributeName,
    NSMenu,
    NSMenuItem,
)
from Foundation import NSMutableDictionary

from .model import Verdict

MARK = {True: "✓", False: "✕", None: "·"}


def _mono_attributed(text: str) -> NSAttributedString:
    """Моноширинный шрифт, чтобы колонки строк не разъезжались."""
    attrs = NSMutableDictionary.dictionary()
    attrs[NSFontAttributeName] = NSFont.monospacedDigitSystemFontOfSize_weight_(12, 0)
    return NSAttributedString.alloc().initWithString_attributes_(text, attrs)


def build(verdict: Verdict, target, *, version: str = "") -> NSMenu:
    """Собрать меню для вердикта.

    `target` — объект, у которого есть методы `refresh:`, `copyReport:` и `quit:`.
    """
    menu = NSMenu.alloc().init()
    menu.setAutoenablesItems_(False)

    headline = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        verdict.headline or "Всё работает", None, ""
    )
    headline.setEnabled_(False)
    menu.addItem_(headline)
    menu.addItem_(NSMenuItem.separatorItem())

    width = max((len(row.label) for row in verdict.details), default=0)
    for row in verdict.details:
        title = f"{MARK[row.ok]}  {row.label.ljust(width)}   {row.value}"
        item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, None, "")
        item.setAttributedTitle_(_mono_attributed(title))
        item.setEnabled_(False)
        menu.addItem_(item)

    menu.addItem_(NSMenuItem.separatorItem())

    refresh = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "Проверить сейчас", "refresh:", "r"
    )
    refresh.setTarget_(target)
    menu.addItem_(refresh)

    copy_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "Скопировать отчёт", "copyReport:", "c"
    )
    copy_item.setTarget_(target)
    menu.addItem_(copy_item)

    menu.addItem_(NSMenuItem.separatorItem())

    quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        f"Выйти из lag-sonar{f' {version}' if version else ''}", "quit:", "q"
    )
    quit_item.setTarget_(target)
    menu.addItem_(quit_item)

    return menu


def report_text(verdict: Verdict) -> str:
    """Тот же расклад простым текстом — чтобы вставить в переписку."""
    lines = [verdict.headline or "Всё работает", ""]
    width = max((len(row.label) for row in verdict.details), default=0)
    for row in verdict.details:
        lines.append(f"{MARK[row.ok]} {row.label.ljust(width)}  {row.value}")
    return "\n".join(lines)
