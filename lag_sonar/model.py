"""Структуры данных, общие для проб, диагностики и отрисовки.

Модуль сознательно не содержит логики и не делает ввода-вывода: его импортируют
и сетевой слой, и чистая диагностика, и UI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RingState(str, Enum):
    """Состояние сети — внешнее кольцо иконки."""

    UNKNOWN = "unknown"  # ещё не мерили или измерение не состоялось
    OK = "ok"
    DNS_DOWN = "dns_down"
    VPN_DOWN = "vpn_down"
    ISP_DOWN = "isp_down"
    NO_LINK = "no_link"


class CoreState(str, Enum):
    """Состояние Claude — ядро иконки."""

    OK = "ok"
    SLOW = "slow"
    BLOCKED = "blocked"
    DOWN = "down"
    INCIDENT = "incident"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Probe:
    """Результат одной пробы.

    `ok` означает «проба дошла до конца и получила ожидаемый ответ», а не просто
    «не было исключения»: для TLS-проб это завершённое рукопожатие, для HTTP —
    полученный статус.
    """

    name: str
    ok: bool
    latency_ms: float | None = None
    detail: str = ""
    skipped: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def skip(cls, name: str, why: str) -> "Probe":
        return cls(name=name, ok=False, detail=why, skipped=True)


@dataclass(frozen=True)
class Topology:
    """Снимок того, как машина сейчас подключена к сети.

    Собирается в `netinfo`, потребляется диагностикой. Диагностике нужно знать,
    активен ли туннель: иначе непрошедшую пробу через маршрут по умолчанию
    не с чем сопоставить.
    """

    phys_iface: str | None = None
    phys_ip: str | None = None
    gateway: str | None = None
    default_iface: str | None = None
    vpn_active: bool = False
    vpn_name: str | None = None

    @property
    def has_link(self) -> bool:
        return bool(self.phys_iface and self.phys_ip)

    def same_shape(self, other: "Topology | None") -> bool:
        """Совпадает ли топология по существу — чтобы заметить смену сети."""
        if other is None:
            return False
        return (
            self.phys_iface == other.phys_iface
            and self.phys_ip == other.phys_ip
            and self.default_iface == other.default_iface
            and self.vpn_active == other.vpn_active
        )


@dataclass(frozen=True)
class DetailRow:
    """Строка расклада по слоям в выпадающем меню."""

    label: str
    value: str
    ok: bool | None  # None — «неизвестно / не проверялось»


@dataclass(frozen=True)
class Verdict:
    """Итог одного цикла: что рисовать и что написать в меню."""

    ring: RingState
    core: CoreState
    headline: str
    details: list[DetailRow] = field(default_factory=list)

    @property
    def all_good(self) -> bool:
        return self.ring is RingState.OK and self.core is CoreState.OK
