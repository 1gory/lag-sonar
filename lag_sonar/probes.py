"""Сетевые пробы.

Каждая проба независима, имеет жёсткий таймаут и никогда не бросает исключение
наружу: неудача — это `Probe(ok=False)`, а не падение приложения.

Два принципа, добытые замерами на живой машине (см. дизайн):

1. Проверка связности доводится до TLS-рукопожатия. Голый `connect()` через
   VPN-туннель возвращается за 0,4 мс, потому что клиент подтверждает соединение
   локально, ничего не доставив, — такая проба показывала бы «всё хорошо»
   на полностью мёртвом канале.

2. Проба Claude различает коды ответа: 401 без ключа означает «API жив
   и доступен», а 403 — «до API не дошли, нас режут по региону».
"""

from __future__ import annotations

import http.client
import json
import socket
import ssl
import struct
import time
import urllib.error
import urllib.request

from . import config
from .model import Probe, Topology

# <netinet/in.h>: привязка сокета к интерфейсу в обход таблицы маршрутизации.
IP_BOUND_IF = 25


def _elapsed_ms(t0: float) -> float:
    return (time.monotonic() - t0) * 1000.0


def _socket_bound_to(iface: str | None, timeout: float) -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    if iface:
        s.setsockopt(
            socket.IPPROTO_IP,
            IP_BOUND_IF,
            struct.pack("I", socket.if_nametoindex(iface)),
        )
    return s


def _short(exc: BaseException) -> str:
    """Короткое человеческое описание сетевой ошибки для меню."""
    if isinstance(exc, socket.timeout) or isinstance(exc, TimeoutError):
        return "таймаут"
    if isinstance(exc, ssl.SSLError):
        return "ошибка TLS"
    if isinstance(exc, socket.gaierror):
        return "имя не разрешается"
    if isinstance(exc, ConnectionRefusedError):
        return "соединение отклонено"
    if isinstance(exc, OSError) and exc.errno == 65:  # EHOSTUNREACH
        return "хост недостижим"
    if isinstance(exc, OSError) and exc.errno == 51:  # ENETUNREACH
        return "сеть недостижима"
    return type(exc).__name__


# --- пробы ------------------------------------------------------------------


def probe_link(topo: Topology) -> Probe:
    """Есть ли вообще физический интерфейс с адресом."""
    if topo.has_link:
        return Probe("link", True, detail=f"{topo.phys_iface} · {topo.phys_ip}")
    return Probe("link", False, detail="нет интерфейса с IPv4")


def probe_gateway(topo: Topology) -> Probe:
    """Отвечает ли роутер.

    Роутеры редко слушают предсказуемый порт, поэтому успехом считается и явный
    отказ в соединении: он означает, что устройство на месте и ответило.
    """
    if not topo.gateway or not topo.phys_iface:
        return Probe.skip("gateway", "шлюз неизвестен")

    t0 = time.monotonic()
    last = ""
    for port in (80, 443, 53):
        s = None
        try:
            s = _socket_bound_to(topo.phys_iface, config.GATEWAY_TIMEOUT)
            s.connect((topo.gateway, port))
            return Probe("gateway", True, _elapsed_ms(t0))
        except ConnectionRefusedError:
            # Порт закрыт, но роутер ответил — значит он жив.
            return Probe("gateway", True, _elapsed_ms(t0), detail="порт закрыт")
        except Exception as exc:  # noqa: BLE001 — любая неудача это просто неудача
            last = _short(exc)
        finally:
            if s is not None:
                s.close()
    return Probe("gateway", False, _elapsed_ms(t0), detail=last or "не отвечает")


def _tls_handshake(host: str, sni: str, iface: str | None, timeout: float) -> float:
    """Полное TLS-рукопожатие. Возвращает длительность в миллисекундах."""
    ctx = ssl.create_default_context()
    t0 = time.monotonic()
    s = _socket_bound_to(iface, timeout)
    try:
        s.connect((host, 443))
        with ctx.wrap_socket(s, server_hostname=sni):
            return _elapsed_ms(t0)
    finally:
        try:
            s.close()
        except OSError:
            pass


def _connectivity(name: str, iface: str | None) -> Probe:
    """Проходит ли трафик наружу по заданному пути.

    Целей две: один провайдер может резать конкретный публичный резолвер,
    и единственная цель дала бы ложную тревогу.
    """
    failures: list[str] = []
    for host, sni in config.CONNECTIVITY_TARGETS:
        try:
            ms = _tls_handshake(host, sni, iface, config.TLS_TIMEOUT)
            return Probe(name, True, ms, extra={"target": host})
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{host}: {_short(exc)}")
    # Перечисляем все цели: сообщение про одну выглядело бы как проблема
    # конкретно с ней, хотя не ответил никто.
    return Probe(name, False, detail=", ".join(failures) or "не проходит")


def probe_direct(topo: Topology) -> Probe:
    """Интернет в обход туннеля — жив ли провайдер."""
    if not topo.phys_iface:
        return Probe.skip("direct", "нет физического интерфейса")
    return _connectivity("direct", topo.phys_iface)


def probe_tunnel(topo: Topology) -> Probe:
    """Интернет по маршруту по умолчанию — пропускает ли VPN."""
    if not topo.vpn_active:
        return Probe.skip("tunnel", "VPN выключен")
    return _connectivity("tunnel", None)


def probe_dns() -> Probe:
    """Разрешается ли имя. Отдельно от связности: ломается независимо."""
    t0 = time.monotonic()
    try:
        socket.setdefaulttimeout(config.DNS_TIMEOUT)
        infos = socket.getaddrinfo(
            config.DNS_PROBE_NAME, 443, socket.AF_INET, socket.SOCK_STREAM
        )
        addr = infos[0][4][0] if infos else "?"
        return Probe("dns", True, _elapsed_ms(t0), extra={"address": addr})
    except Exception as exc:  # noqa: BLE001
        return Probe("dns", False, _elapsed_ms(t0), detail=_short(exc))
    finally:
        socket.setdefaulttimeout(None)


def probe_claude_api() -> Probe:
    """Запрос к API без ключа.

    Ожидаемый ответ — 401: он доказывает, что запрос дошёл до Anthropic и был
    разобран. 403 означает обратное — нас отсекли по дороге.
    """
    host, path = config.CLAUDE_HOST, config.CLAUDE_PATH
    t0 = time.monotonic()
    conn = None
    try:
        # Явный IPv4: имя резолвится только в A-запись, а обход через
        # системный стек добавил бы к замеру чужие задержки.
        ip = socket.getaddrinfo(host, 443, socket.AF_INET, socket.SOCK_STREAM)[0][4][0]
        sock = socket.create_connection((ip, 443), timeout=config.CLAUDE_TIMEOUT)
        tls = ssl.create_default_context().wrap_socket(sock, server_hostname=host)
        conn = http.client.HTTPConnection(host, timeout=config.CLAUDE_TIMEOUT)
        conn.sock = tls
        conn.request("GET", path, headers={"Host": host, "User-Agent": config.USER_AGENT})
        response = conn.getresponse()
        response.read(512)
        ms = _elapsed_ms(t0)

        status = response.status
        extra = {"status": status, "address": ip}
        if status == 401:
            return Probe("claude_api", True, ms, extra=extra)
        if status == 403:
            return Probe(
                "claude_api", False, ms, detail="доступ заблокирован", extra=extra
            )
        if 200 <= status < 500:
            # Неожиданный, но осмысленный ответ: API на связи.
            return Probe("claude_api", True, ms, detail=f"HTTP {status}", extra=extra)
        return Probe("claude_api", False, ms, detail=f"HTTP {status}", extra=extra)
    except Exception as exc:  # noqa: BLE001
        return Probe("claude_api", False, _elapsed_ms(t0), detail=_short(exc))
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


def probe_claude_status() -> Probe:
    """Официальная статус-страница Anthropic."""
    t0 = time.monotonic()
    try:
        request = urllib.request.Request(
            config.STATUS_URL, headers={"User-Agent": config.USER_AGENT}
        )
        with urllib.request.urlopen(request, timeout=config.STATUS_TIMEOUT) as response:
            payload = json.loads(response.read(8192))
        status = payload.get("status", {})
        return Probe(
            "claude_status",
            True,
            _elapsed_ms(t0),
            extra={
                "indicator": status.get("indicator", "none"),
                "description": status.get("description", ""),
            },
        )
    except Exception as exc:  # noqa: BLE001
        return Probe("claude_status", False, _elapsed_ms(t0), detail=_short(exc))
