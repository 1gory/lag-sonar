"""Снимок сетевой топологии машины.

Только факты: какой интерфейс физический, какой у него адрес, куда ведёт
маршрут по умолчанию и поднят ли VPN. Никаких выводов — их делает `diagnosis`.

Список интерфейсов берётся через `getifaddrs`, чтобы не платить за запуск
процесса на каждом цикле. Маршрут по умолчанию и имя VPN читаются утилитами
`route` и `scutil` с кэшированием: они меняются редко.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import socket
import subprocess
import time
from dataclasses import dataclass

from . import config
from .model import Topology

# --- getifaddrs через ctypes ------------------------------------------------


class _sockaddr(ctypes.Structure):
    _fields_ = [
        ("sa_len", ctypes.c_uint8),
        ("sa_family", ctypes.c_uint8),
        ("sa_data", ctypes.c_char * 14),
    ]


class _sockaddr_in(ctypes.Structure):
    _fields_ = [
        ("sin_len", ctypes.c_uint8),
        ("sin_family", ctypes.c_uint8),
        ("sin_port", ctypes.c_uint16),
        ("sin_addr", ctypes.c_uint8 * 4),
        ("sin_zero", ctypes.c_char * 8),
    ]


class _ifaddrs(ctypes.Structure):
    pass


_ifaddrs._fields_ = [
    ("ifa_next", ctypes.POINTER(_ifaddrs)),
    ("ifa_name", ctypes.c_char_p),
    ("ifa_flags", ctypes.c_uint),
    ("ifa_addr", ctypes.POINTER(_sockaddr)),
    ("ifa_netmask", ctypes.POINTER(_sockaddr)),
    ("ifa_dstaddr", ctypes.POINTER(_sockaddr)),
    ("ifa_data", ctypes.c_void_p),
]

_libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
_libc.getifaddrs.restype = ctypes.c_int
_libc.getifaddrs.argtypes = [ctypes.POINTER(ctypes.POINTER(_ifaddrs))]
_libc.freeifaddrs.argtypes = [ctypes.POINTER(_ifaddrs)]

IFF_UP = 0x1
IFF_RUNNING = 0x40


@dataclass(frozen=True)
class Interface:
    name: str
    ipv4: str

    @property
    def index(self) -> int:
        return socket.if_nametoindex(self.name)


def list_ipv4_interfaces() -> list[Interface]:
    """Интерфейсы, у которых есть поднятый IPv4-адрес."""
    head = ctypes.POINTER(_ifaddrs)()
    if _libc.getifaddrs(ctypes.byref(head)) != 0:
        return []
    found: list[Interface] = []
    try:
        node = head
        while node:
            entry = node.contents
            name = entry.ifa_name.decode() if entry.ifa_name else ""
            flags = entry.ifa_flags
            if (
                name
                and entry.ifa_addr
                and entry.ifa_addr.contents.sa_family == socket.AF_INET
                and flags & IFF_UP
                and flags & IFF_RUNNING
            ):
                sin = ctypes.cast(entry.ifa_addr, ctypes.POINTER(_sockaddr_in)).contents
                ip = ".".join(str(b) for b in sin.sin_addr)
                if ip != "127.0.0.1":
                    found.append(Interface(name=name, ipv4=ip))
            node = entry.ifa_next
    finally:
        _libc.freeifaddrs(head)
    return found


# --- классификация ----------------------------------------------------------


def is_virtual(name: str) -> bool:
    return name.startswith(config.VIRTUAL_IFACE_PREFIXES)


def is_tunnel(name: str) -> bool:
    return name.startswith(config.TUNNEL_IFACE_PREFIXES)


def pick_physical(
    candidates: list[Interface], default_iface: str | None
) -> Interface | None:
    """Выбрать интерфейс, через который машина реально подключена к сети.

    Приоритет: интерфейс маршрута по умолчанию (если он не туннель), затем
    настоящая сетевая карта `en*`, затем прочие. Мосты (`bridge*` для виртуалок
    и Thunderbolt) имеют маршрутизируемый адрес, но наружу не ведут, поэтому
    идут последними. Самоназначенный 169.254.x берётся только за неимением
    лучшего: через него всё равно не выйти.
    """
    real = [c for c in candidates if not is_virtual(c.name)]
    if not real:
        return None

    def rank(iface: Interface) -> tuple[int, int]:
        link_local = iface.ipv4.startswith("169.254.")
        if iface.name == default_iface:
            kind = 0
        elif iface.name.startswith("en"):
            kind = 1
        else:
            kind = 2
        return (int(link_local), kind)

    return min(real, key=rank)


# --- системные утилиты ------------------------------------------------------


def parse_route_default(text: str) -> tuple[str | None, str | None]:
    """Разобрать вывод `route -n get default` → (интерфейс, шлюз).

    При маршруте через туннель строки `gateway` нет — это нормально
    и означает point-to-point.
    """
    iface = gateway = None
    for line in text.splitlines():
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if key == "interface":
            iface = value or None
        elif key == "gateway":
            gateway = value or None
    return iface, gateway


def parse_scutil_nc(text: str) -> str | None:
    """Имя подключённого VPN из `scutil --nc list`.

    PPP-модемы (у пользователя это фитнес-браслет) тоже попадают в список
    и тоже бывают Connected, но VPN они не являются.
    """
    for line in text.splitlines():
        if "(Connected)" not in line or "[VPN:" not in line:
            continue
        start = line.find('"')
        end = line.find('"', start + 1)
        if start != -1 and end != -1:
            return line[start + 1 : end]
    return None


def _run(cmd: list[str], timeout: float = 2.0) -> str:
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        ).stdout
    except Exception:
        return ""


# --- сборка снимка ----------------------------------------------------------

_ROUTE_TTL = 5.0
_VPN_TTL = 30.0

_route_cache: tuple[float, tuple[str | None, str | None]] | None = None
_vpn_cache: tuple[float, str | None] | None = None


def _default_route() -> tuple[str | None, str | None]:
    global _route_cache
    now = time.monotonic()
    if _route_cache and now - _route_cache[0] < _ROUTE_TTL:
        return _route_cache[1]
    parsed = parse_route_default(_run(["/sbin/route", "-n", "get", "default"]))
    _route_cache = (now, parsed)
    return parsed


def _vpn_name() -> str | None:
    global _vpn_cache
    now = time.monotonic()
    if _vpn_cache and now - _vpn_cache[0] < _VPN_TTL:
        return _vpn_cache[1]
    name = parse_scutil_nc(_run(["/usr/sbin/scutil", "--nc", "list"]))
    _vpn_cache = (now, name)
    return name


def _gateway_for(iface: str) -> str | None:
    """Шлюз конкретного интерфейса — нужен, когда маршрут по умолчанию в туннеле."""
    _, gw = parse_route_default(
        _run(["/sbin/route", "-n", "get", "-ifscope", iface, "default"])
    )
    return gw


def snapshot() -> Topology:
    """Собрать текущее состояние подключения."""
    default_iface, default_gw = _default_route()
    interfaces = list_ipv4_interfaces()
    phys = pick_physical(interfaces, default_iface)

    vpn_active = bool(default_iface and is_tunnel(default_iface))
    vpn_name = _vpn_name() if vpn_active else None

    gateway = default_gw
    if phys and (gateway is None or vpn_active):
        gateway = _gateway_for(phys.name) or gateway

    return Topology(
        phys_iface=phys.name if phys else None,
        phys_ip=phys.ipv4 if phys else None,
        gateway=gateway,
        default_iface=default_iface,
        vpn_active=vpn_active,
        vpn_name=vpn_name or (default_iface if vpn_active else None),
    )
