"""Приложение menu bar: значок, таймер и склейка всего остального.

Единственное место, где живёт состояние UI. Правило: в главном потоке не
выполняется ни одной сетевой операции — иначе панель меню подвисает на время
таймаута, и это сразу видно.
"""

from __future__ import annotations

import logging
import os
import sys
import threading

import objc
from AppKit import (
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSPasteboard,
    NSPasteboardTypeString,
    NSStatusBar,
    NSVariableStatusItemLength,
    NSWorkspace,
)
from Foundation import NSObject, NSTimer
from PyObjCTools import AppHelper

from . import __version__, config, icon, menu as menu_module
from .runner import UNMEASURED, Monitor

log = logging.getLogger("lag_sonar")


def _setup_logging() -> None:
    config.LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=str(config.LOG_PATH),
        level=logging.INFO,
        # Явно: у запущенного из Finder приложения нет UTF-8-локали,
        # и без этого кириллица в журнале превращается в \uXXXX.
        encoding="utf-8",
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _layers(verdict) -> str:
    """Расклад по слоям одной строкой: `+` работает, `-` сломан, `·` не проверялся."""
    mark = {True: "+", False: "-", None: "·"}
    return "; ".join(f"{mark[row.ok]}{row.label}: {row.value}" for row in verdict.details)


class LagSonarController(NSObject):
    """Контроллер значка в menu bar."""

    def initWithMonitor_(self, monitor):
        self = objc.super(LagSonarController, self).init()
        if self is None:
            return None

        self._monitor = monitor
        self._verdict = UNMEASURED
        self._timer = None
        self._busy = False

        self._status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(
            NSVariableStatusItemLength
        )
        self._status_item.button().setImage_(
            icon.render(UNMEASURED.ring, UNMEASURED.core)
        )
        self._status_item.button().setToolTip_(UNMEASURED.headline)
        self._rebuild_menu()

        NSWorkspace.sharedWorkspace().notificationCenter().addObserver_selector_name_object_(
            self, "wakeFromSleep:", "NSWorkspaceDidWakeNotification", None
        )

        self._start_cycle()
        return self

    # --- цикл измерения -----------------------------------------------------

    @objc.python_method
    def _start_cycle(self) -> None:
        """Запустить измерение в фоне. Главный поток не блокируется."""
        if self._busy:
            return
        self._busy = True
        threading.Thread(target=self._measure, name="lag-sonar-cycle", daemon=True).start()

    @objc.python_method
    def _measure(self) -> None:
        try:
            verdict = self._monitor.tick()
        except Exception as exc:  # noqa: BLE001
            log.exception("цикл измерения упал: %r", exc)
            verdict = self._verdict
        AppHelper.callAfter(self._apply, verdict)

    @objc.python_method
    def _apply(self, verdict) -> None:
        """Обновить значок и меню. Вызывается только в главном потоке."""
        self._busy = False
        previous = self._verdict
        self._verdict = verdict

        # Пишем только переходы: запись каждого цикла раздула бы журнал,
        # а интересны именно моменты, когда что-то сломалось или починилось.
        # Расклад по слоям пишется вместе с переходом — по одному заголовку
        # задним числом не понять, какой слой и насколько тормозил.
        if (previous.ring, previous.core) != (verdict.ring, verdict.core):
            log.info(
                "%s/%s -> %s/%s · %s | %s",
                previous.ring.value,
                previous.core.value,
                verdict.ring.value,
                verdict.core.value,
                verdict.headline,
                _layers(verdict),
            )
        try:
            self._status_item.button().setImage_(icon.render(verdict.ring, verdict.core))
            self._status_item.button().setToolTip_(verdict.headline or "Всё работает")
            self._rebuild_menu()
        except Exception as exc:  # noqa: BLE001
            log.exception("не удалось обновить значок: %r", exc)
        self._schedule(self._monitor.interval)

    @objc.python_method
    def _schedule(self, delay: float) -> None:
        if self._timer is not None:
            self._timer.invalidate()
        self._timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            delay, self, "timerFired:", None, False
        )

    @objc.python_method
    def _rebuild_menu(self) -> None:
        self._status_item.setMenu_(
            menu_module.build(self._verdict, self, version=__version__)
        )

    # --- действия -----------------------------------------------------------

    def timerFired_(self, _timer) -> None:
        self._start_cycle()

    def wakeFromSleep_(self, _notification) -> None:
        """После пробуждения состояние сети почти наверняка другое."""
        log.info("пробуждение из сна — внеочередная проверка")
        self._start_cycle()

    def refresh_(self, _sender) -> None:
        self._start_cycle()

    def copyReport_(self, _sender) -> None:
        pasteboard = NSPasteboard.generalPasteboard()
        pasteboard.clearContents()
        pasteboard.setString_forType_(
            menu_module.report_text(self._verdict), NSPasteboardTypeString
        )

    def quit_(self, _sender) -> None:
        NSApplication.sharedApplication().terminate_(self)


def _use_system_certs() -> None:
    """В собранном .app взять системные корневые сертификаты.

    OpenSSL из python.org ищет их в каталоге установленного Python. Внутри
    автономного приложения этого каталога на чужом маке нет, и все TLS-пробы
    падали бы с ошибкой проверки сертификата — значок врал бы «Claude не отвечает».
    """
    system_bundle = "/etc/ssl/cert.pem"
    if getattr(sys, "frozen", False) and "SSL_CERT_FILE" not in os.environ:
        if os.path.exists(system_bundle):
            os.environ["SSL_CERT_FILE"] = system_bundle


def main(argv: list[str] | None = None) -> int:
    _use_system_certs()
    _setup_logging()
    log.info("lag-sonar %s запускается", __version__)

    app = NSApplication.sharedApplication()
    # Accessory: без значка в Dock и без окна — только menu bar.
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    controller = LagSonarController.alloc().initWithMonitor_(Monitor())
    app.setDelegate_(controller)

    AppHelper.runEventLoop(installInterrupt=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
