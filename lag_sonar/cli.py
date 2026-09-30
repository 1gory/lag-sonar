"""Тот же вердикт, что показывает иконка, но текстом в терминале.

Нужен, чтобы проверять диагностику на живой сети, не поднимая GUI, и чтобы
было куда посмотреть, когда иконка говорит о проблеме, а хочется подробностей.
"""

from __future__ import annotations

import argparse
import sys
import time

from .model import CoreState, RingState, Verdict
from .runner import Monitor

RESET = "\033[0m"
DIM = "\033[2m"
BOLD = "\033[1m"

RING_LABEL = {
    RingState.OK: ("\033[32m", "сеть в порядке"),
    RingState.DNS_DOWN: ("\033[33m", "DNS не резолвит"),
    RingState.VPN_DOWN: ("\033[35m", "VPN не пропускает"),
    RingState.ISP_DOWN: ("\033[31m", "сеть не работает"),
    RingState.NO_LINK: ("\033[90m", "нет линка"),
    RingState.UNKNOWN: ("\033[90m", "неизвестно"),
}

CORE_LABEL = {
    CoreState.OK: ("\033[32m", "Claude отвечает"),
    CoreState.SLOW: ("\033[33m", "Claude тормозит"),
    CoreState.BLOCKED: ("\033[35m", "Claude заблокирован"),
    CoreState.DOWN: ("\033[31m", "Claude не отвечает"),
    CoreState.INCIDENT: ("\033[31m", "авария у Anthropic"),
    CoreState.UNKNOWN: ("\033[90m", "Claude — неизвестно"),
}

MARK = {True: "\033[32m✓\033[0m", False: "\033[31m✕\033[0m", None: f"{DIM}·{RESET}"}


def render(verdict: Verdict, color: bool = True) -> str:
    def paint(code: str, text: str) -> str:
        return f"{code}{text}{RESET}" if color else text

    ring_color, ring_text = RING_LABEL[verdict.ring]
    core_color, core_text = CORE_LABEL[verdict.core]

    lines = [
        f"{paint(ring_color, '◎')} {paint(BOLD, verdict.headline or 'Всё работает')}",
        f"  {paint(ring_color, ring_text)} · {paint(core_color, core_text)}",
        "",
    ]
    width = max((len(row.label) for row in verdict.details), default=0)
    for row in verdict.details:
        mark = MARK[row.ok] if color else {True: "+", False: "-", None: " "}[row.ok]
        lines.append(f"  {mark} {row.label.ljust(width)}  {row.value}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="lag-sonar", description="Диагностика сети по слоям: сеть, VPN, Claude"
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="повторять опрос, пока не прервут (Ctrl+C)",
    )
    parser.add_argument("--no-color", action="store_true", help="без ANSI-цветов")
    args = parser.parse_args(argv)

    monitor = Monitor()
    try:
        while True:
            started = time.monotonic()
            verdict = monitor.tick()
            if args.watch:
                sys.stdout.write("\033[2J\033[H" if not args.no_color else "\n")
            print(render(verdict, color=not args.no_color))
            if not args.watch:
                return 0 if verdict.all_good else 1
            print(f"\n{DIM}цикл {time.monotonic() - started:.1f} с · "
                  f"следующий через {monitor.interval:.0f} с · Ctrl+C для выхода{RESET}")
            time.sleep(monitor.interval)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
