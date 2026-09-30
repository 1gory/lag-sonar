"""Превращение набора проб в вердикт.

Здесь живёт вся содержательная логика приложения, и здесь же нет ни одного
обращения к сети: на вход подаются готовые `Probe`, на выход идёт `Verdict`.
Благодаря этому таблицу состояний целиком можно проверить офлайн.
"""

from __future__ import annotations

from . import config
from .model import CoreState, DetailRow, Probe, RingState, Topology, Verdict

# Индикаторы статус-страницы, которые перевешивают даже удачную пробу:
# если у них объявлена крупная авария, знать об этом полезнее, чем видеть
# зелёное ядро из-за того, что конкретно наш запрос прошёл.
SEVERE_INDICATORS = frozenset({"major", "critical"})

# С какого возраста замер помечается в меню как несвежий.
STALE_AFTER_S = 5.0


def _probe(probes: dict[str, Probe], name: str) -> Probe | None:
    return probes.get(name)


def _ok(probes: dict[str, Probe], name: str) -> bool:
    p = probes.get(name)
    return bool(p and p.ok)


def _ms(p: Probe | None) -> str:
    if p is None or p.latency_ms is None:
        return "—"
    if p.latency_ms >= 1000:
        return f"{p.latency_ms / 1000:.1f} с"
    return f"{p.latency_ms:.0f} мс"


def _ring_state(probes: dict[str, Probe], topo: Topology) -> RingState:
    """Самый нижний сломанный слой сети — его и надо чинить."""
    if not _ok(probes, "link"):
        return RingState.NO_LINK

    direct_ok = _ok(probes, "direct")
    tunnel = _probe(probes, "tunnel")
    tunnel_relevant = topo.vpn_active and tunnel is not None and not tunnel.skipped
    tunnel_ok = bool(tunnel and tunnel.ok)

    # Наружу вообще ничего не проходит — виноват провайдер или роутер,
    # и разбираться с VPN до починки провайдера бессмысленно.
    if not direct_ok and not (tunnel_relevant and tunnel_ok):
        return RingState.ISP_DOWN

    # Провайдер жив, а туннель молчит: виноват именно VPN.
    if tunnel_relevant and not tunnel_ok:
        return RingState.VPN_DOWN

    if not _ok(probes, "dns"):
        return RingState.DNS_DOWN

    return RingState.OK


def _status_indicator(probes: dict[str, Probe]) -> tuple[str | None, str]:
    p = _probe(probes, "claude_status")
    if p is None or not p.ok:
        return None, ""
    return p.extra.get("indicator"), p.extra.get("description", "")


def _core_state(
    probes: dict[str, Probe], ring: RingState
) -> tuple[CoreState, str]:
    api = _probe(probes, "claude_api")
    indicator, description = _status_indicator(probes)
    severe = indicator in SEVERE_INDICATORS

    if api is None:
        return CoreState.UNKNOWN, "Проба Claude не выполнялась"

    status = api.extra.get("status")

    # 403 — запрос до API не дошёл: нас отсекли по региону. Это отдельная беда,
    # которая лечится включением VPN, а не ожиданием.
    if status == 403:
        return (
            CoreState.BLOCKED,
            "Claude недоступен: доступ заблокирован, нужен рабочий VPN",
        )

    if api.ok:
        if severe:
            return (
                CoreState.INCIDENT,
                f"У Anthropic авария: {description}" if description else "У Anthropic авария",
            )
        if api.latency_ms is not None and api.latency_ms > config.CLAUDE_SLOW_MS:
            return CoreState.SLOW, f"Claude отвечает медленно: {_ms(api)}"
        return CoreState.OK, "Claude отвечает нормально"

    # Проба провалилась. Если сеть сломана, виновата сеть — не надо
    # показывать красное там, где мы просто не смогли спросить.
    if ring is not RingState.OK:
        return CoreState.UNKNOWN, "Состояние Claude неизвестно: нет связи"

    if severe or indicator not in (None, "none"):
        return (
            CoreState.INCIDENT,
            f"У Anthropic авария: {description}" if description else "У Anthropic авария",
        )

    return CoreState.DOWN, f"Claude не отвечает: {api.detail or 'нет ответа'}"


def _ring_headline(ring: RingState, probes: dict[str, Probe], topo: Topology) -> str:
    if ring is RingState.NO_LINK:
        return "Сети нет: интерфейс без адреса"
    if ring is RingState.ISP_DOWN:
        if not _ok(probes, "gateway") and topo.gateway:
            return "Сеть не работает: роутер не отвечает"
        return "Сеть не работает: провайдер не пропускает трафик"
    if ring is RingState.VPN_DOWN:
        name = topo.vpn_name or "VPN"
        return f"Интернет есть, но {name} не пропускает трафик"
    if ring is RingState.DNS_DOWN:
        return "Связь есть, но DNS не резолвит имена"
    return ""


def _details(
    probes: dict[str, Probe], topo: Topology, core_line: str
) -> list[DetailRow]:
    rows: list[DetailRow] = []

    link = _probe(probes, "link")
    rows.append(
        DetailRow(
            label="Wi-Fi / кабель",
            value=(f"{topo.phys_iface} · {topo.phys_ip}" if topo.has_link else "нет адреса"),
            ok=bool(link and link.ok),
        )
    )

    gw = _probe(probes, "gateway")
    if gw is not None and not gw.skipped:
        rows.append(
            DetailRow(
                label="Роутер",
                value=f"{topo.gateway or '—'} · {_ms(gw)}" if gw.ok else (gw.detail or "не отвечает"),
                ok=gw.ok,
            )
        )

    direct = _probe(probes, "direct")
    rows.append(
        DetailRow(
            label="Интернет напрямую",
            value=_ms(direct) if direct and direct.ok else (direct.detail if direct else "—"),
            ok=(direct.ok if direct and not direct.skipped else None),
        )
    )

    tunnel = _probe(probes, "tunnel")
    if topo.vpn_active:
        overhead = ""
        if tunnel and tunnel.ok and direct and direct.ok and direct.latency_ms and tunnel.latency_ms:
            delta = tunnel.latency_ms - direct.latency_ms
            overhead = f" (+{delta:.0f} мс к прямому)" if delta > 0 else ""
        rows.append(
            DetailRow(
                label=f"VPN · {topo.vpn_name or topo.default_iface or 'туннель'}",
                value=(f"{_ms(tunnel)}{overhead}" if tunnel and tunnel.ok
                       else (tunnel.detail if tunnel else "не проверялся")),
                ok=(tunnel.ok if tunnel and not tunnel.skipped else None),
            )
        )
    else:
        rows.append(DetailRow(label="VPN", value="выключен", ok=None))

    dns = _probe(probes, "dns")
    rows.append(
        DetailRow(
            label="DNS",
            value=_ms(dns) if dns and dns.ok else (dns.detail if dns else "—"),
            ok=(dns.ok if dns and not dns.skipped else None),
        )
    )

    api = _probe(probes, "claude_api")
    if api is not None:
        status = api.extra.get("status")
        suffix = f" · HTTP {status}" if status else ""
        # API опрашивается реже сети, поэтому цифра может быть несвежей —
        # без пометки её приняли бы за текущую.
        age = api.extra.get("age_s", 0.0)
        if age >= STALE_AFTER_S:
            suffix += f" · {age:.0f} с назад"
        rows.append(
            DetailRow(
                label="Claude API",
                value=(f"{_ms(api)}{suffix}" if api.latency_ms is not None
                       else (api.detail or "нет ответа")),
                ok=api.ok,
            )
        )

    indicator, description = _status_indicator(probes)
    if indicator is not None:
        rows.append(
            DetailRow(
                label="Статус Anthropic",
                value=description or indicator,
                ok=(indicator == "none"),
            )
        )

    return rows


def diagnose(probes: dict[str, Probe], topo: Topology) -> Verdict:
    """Собрать вердикт по результатам проб.

    Функция чистая: одинаковый вход всегда даёт одинаковый выход.
    """
    ring = _ring_state(probes, topo)
    core, core_line = _core_state(probes, ring)

    ring_line = _ring_headline(ring, probes, topo)
    if ring_line and core in (CoreState.UNKNOWN,):
        headline = ring_line
    elif ring_line:
        headline = f"{ring_line}. {core_line}"
    else:
        headline = core_line

    return Verdict(
        ring=ring,
        core=core,
        headline=headline,
        details=_details(probes, topo, core_line),
    )
