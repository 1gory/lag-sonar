"""Таблица истинности диагностики.

Здесь проверяется вся содержательная логика приложения. Тесты полностью офлайн:
на вход подаются выдуманные наборы проб, на выходе сверяется вердикт.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lag_sonar.diagnosis import diagnose
from lag_sonar.model import CoreState, Probe, RingState, Topology

LINKED = Topology(
    phys_iface="en0",
    phys_ip="192.168.0.248",
    gateway="192.168.0.1",
    default_iface="utun8",
    vpn_active=True,
    vpn_name="PepperVPN",
)

NO_VPN = Topology(
    phys_iface="en0",
    phys_ip="192.168.0.248",
    gateway="192.168.0.1",
    default_iface="en0",
    vpn_active=False,
)

UNPLUGGED = Topology()


def probes(**overrides) -> dict[str, Probe]:
    """Набор проб «всё хорошо», поверх которого тесты кладут поломки."""
    base = {
        "link": Probe("link", True, detail="en0 192.168.0.248"),
        "gateway": Probe("gateway", True, latency_ms=3.0),
        "direct": Probe("direct", True, latency_ms=55.0),
        "tunnel": Probe("tunnel", True, latency_ms=240.0),
        "dns": Probe("dns", True, latency_ms=5.0),
        "claude_api": Probe(
            "claude_api", True, latency_ms=700.0, extra={"status": 401}
        ),
        "claude_status": Probe(
            "claude_status", True, latency_ms=900.0, extra={"indicator": "none"}
        ),
    }
    base.update(overrides)
    return base


def fail(name: str, detail: str = "timeout") -> Probe:
    return Probe(name, False, detail=detail)


# --- кольцо: состояние сети -------------------------------------------------


def test_everything_healthy_gives_green_ring_and_green_core():
    v = diagnose(probes(), LINKED)
    assert v.ring is RingState.OK
    assert v.core is CoreState.OK
    assert v.all_good


def test_no_link_when_interface_has_no_address():
    v = diagnose(
        probes(
            link=fail("link", "нет интерфейса с IPv4"),
            gateway=Probe.skip("gateway", "нет линка"),
            direct=Probe.skip("direct", "нет линка"),
            tunnel=fail("tunnel"),
            dns=fail("dns"),
            claude_api=fail("claude_api"),
        ),
        UNPLUGGED,
    )
    assert v.ring is RingState.NO_LINK


def test_isp_down_when_nothing_gets_out():
    """Ни напрямую, ни через туннель — виноват провайдер, не VPN."""
    v = diagnose(
        probes(direct=fail("direct"), tunnel=fail("tunnel"), dns=fail("dns")),
        LINKED,
    )
    assert v.ring is RingState.ISP_DOWN


def test_vpn_down_when_direct_works_but_tunnel_does_not():
    """Главное различение: провайдер жив, туннель — нет."""
    v = diagnose(probes(tunnel=fail("tunnel")), LINKED)
    assert v.ring is RingState.VPN_DOWN


def test_tunnel_failure_ignored_when_vpn_is_off():
    """Без VPN проба через маршрут по умолчанию — это и есть direct."""
    v = diagnose(probes(tunnel=Probe.skip("tunnel", "VPN выключен")), NO_VPN)
    assert v.ring is RingState.OK


def test_direct_failure_tolerated_when_tunnel_works():
    """Провайдер режет 1.1.1.1, но через VPN всё ходит — это рабочая сеть."""
    v = diagnose(probes(direct=fail("direct", "провайдер режет")), LINKED)
    assert v.ring is RingState.OK


def test_dns_down_when_connectivity_is_fine_but_names_do_not_resolve():
    v = diagnose(probes(dns=fail("dns", "NXDOMAIN")), LINKED)
    assert v.ring is RingState.DNS_DOWN


def test_isp_beats_vpn_and_dns_in_priority():
    """При множественной поломке показываем самый нижний слой."""
    v = diagnose(
        probes(direct=fail("direct"), tunnel=fail("tunnel"), dns=fail("dns")),
        LINKED,
    )
    assert v.ring is RingState.ISP_DOWN


def test_no_link_beats_everything():
    v = diagnose(
        probes(
            link=fail("link"),
            direct=fail("direct"),
            tunnel=fail("tunnel"),
            dns=fail("dns"),
        ),
        UNPLUGGED,
    )
    assert v.ring is RingState.NO_LINK


# --- ядро: состояние Claude -------------------------------------------------


def test_core_slow_when_api_answers_past_threshold():
    v = diagnose(
        probes(
            claude_api=Probe(
                "claude_api", True, latency_ms=2400.0, extra={"status": 401}
            )
        ),
        LINKED,
    )
    assert v.ring is RingState.OK
    assert v.core is CoreState.SLOW


def test_core_blocked_on_403():
    """403 означает, что до API не доходим: региональная блокировка."""
    v = diagnose(
        probes(
            claude_api=Probe(
                "claude_api", False, latency_ms=110.0, extra={"status": 403}
            )
        ),
        LINKED,
    )
    assert v.core is CoreState.BLOCKED


def test_core_down_when_network_is_fine_but_api_is_not():
    """Ровно тот случай, ради которого всё затевалось."""
    v = diagnose(probes(claude_api=fail("claude_api", "handshake timeout")), LINKED)
    assert v.ring is RingState.OK
    assert v.core is CoreState.DOWN


def test_core_unknown_when_network_is_broken():
    """Судить о Claude, не имея сети, нельзя — и не надо врать красным."""
    v = diagnose(
        probes(
            direct=fail("direct"),
            tunnel=fail("tunnel"),
            dns=fail("dns"),
            claude_api=fail("claude_api"),
        ),
        LINKED,
    )
    assert v.ring is RingState.ISP_DOWN
    assert v.core is CoreState.UNKNOWN


def test_core_incident_when_status_page_confirms_outage():
    v = diagnose(
        probes(
            claude_api=fail("claude_api", "503"),
            claude_status=Probe(
                "claude_status",
                True,
                extra={"indicator": "major", "description": "Elevated errors"},
            ),
        ),
        LINKED,
    )
    assert v.core is CoreState.INCIDENT


def test_major_incident_shown_even_when_probe_succeeds():
    """API отвечает нам, но у них объявлена крупная авария — это стоит знать."""
    v = diagnose(
        probes(
            claude_status=Probe(
                "claude_status",
                True,
                extra={"indicator": "critical", "description": "Major outage"},
            )
        ),
        LINKED,
    )
    assert v.core is CoreState.INCIDENT


def test_minor_incident_does_not_override_healthy_probe():
    v = diagnose(
        probes(
            claude_status=Probe(
                "claude_status",
                True,
                extra={"indicator": "minor", "description": "Degraded docs"},
            )
        ),
        LINKED,
    )
    assert v.core is CoreState.OK


def test_status_probe_failure_is_not_an_incident():
    """Недоступная статус-страница — не повод обвинять API."""
    v = diagnose(probes(claude_status=fail("claude_status")), LINKED)
    assert v.core is CoreState.OK


# --- пояснения для человека -------------------------------------------------


def test_headline_names_the_culprit():
    cases = [
        (probes(tunnel=fail("tunnel")), LINKED, "VPN"),
        (probes(dns=fail("dns")), LINKED, "DNS"),
        (probes(claude_api=fail("claude_api")), LINKED, "Claude"),
    ]
    for p, topo, expected_word in cases:
        assert expected_word in diagnose(p, topo).headline


def test_details_cover_every_layer():
    v = diagnose(probes(), LINKED)
    labels = " ".join(row.label for row in v.details)
    for word in ("Wi-Fi", "Интернет", "VPN", "DNS", "Claude"):
        assert word in labels


def test_stale_claude_measurement_is_marked_as_such():
    """API опрашивается реже сети: несвежую цифру нельзя выдавать за текущую."""
    v = diagnose(
        probes(
            claude_api=Probe(
                "claude_api", True, 700.0, extra={"status": 401, "age_s": 27.0}
            )
        ),
        LINKED,
    )
    row = next(r for r in v.details if r.label == "Claude API")
    assert "27 с назад" in row.value


def test_fresh_claude_measurement_has_no_age_suffix():
    v = diagnose(probes(), LINKED)
    row = next(r for r in v.details if r.label == "Claude API")
    assert "назад" not in row.value


def test_details_report_measured_latency():
    v = diagnose(probes(), LINKED)
    values = " ".join(row.value for row in v.details)
    assert "700" in values  # задержка Claude попала в меню


def test_vpn_row_absent_when_vpn_is_off():
    v = diagnose(probes(tunnel=Probe.skip("tunnel", "VPN выключен")), NO_VPN)
    vpn_rows = [r for r in v.details if r.label.startswith("VPN")]
    assert vpn_rows and vpn_rows[0].ok is None


@pytest.mark.parametrize("missing", ["gateway", "claude_status"])
def test_missing_probe_does_not_crash(missing):
    """Приложение переживает отсутствие любой необязательной пробы."""
    p = probes()
    del p[missing]
    v = diagnose(p, LINKED)
    assert v.ring is RingState.OK
