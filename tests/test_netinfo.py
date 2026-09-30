"""Разбор вывода системных утилит на зафиксированных образцах.

Образцы сняты с живой машины 2026-09-30, чтобы разбор проверялся против
настоящего формата, а не против выдуманного.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lag_sonar.netinfo import (
    Interface,
    is_tunnel,
    is_virtual,
    parse_route_default,
    parse_scutil_nc,
    pick_physical,
)

ROUTE_VIA_VPN = """   route to: default
destination: default
       mask: default
  interface: utun8
      flags: <UP,DONE,CLONING,STATIC,GLOBAL>
 recvpipe  sendpipe  ssthresh  rtt,msec    rttvar  hopcount      mtu     expire
       0         0         0         0         0         0      1500         0
"""

ROUTE_VIA_WIFI = """   route to: default
destination: default
       mask: default
    gateway: 192.168.0.1
  interface: en0
      flags: <UP,GATEWAY,DONE,STATIC,PRCLONING,GLOBAL>
"""

SCUTIL_NC = """Available network connection services in the current set (*=enabled):
* (Disconnected)   F9CF603C-81A8-4534-BB6E-0231D7161240 PPP --> Healbe Gobe (BaseFW) "Healbe Gobe (BaseFW) 2"         [PPP:Modem]
* (Connected)      F8F6CC2D-A2BD-409C-959D-5A646C247F44 VPN (info.peppervpn.app) "PepperVPN"                      [VPN:info.peppervpn.app]
* (Disconnected)   69A114EE-9C09-4C3E-9DF6-A89CD12FE5AD VPN (hossin.asaadi.V2Box) "V2BOX"                          [VPN:hossin.asaadi.V2Box]
"""


def test_parse_route_through_tunnel_has_no_gateway():
    iface, gateway = parse_route_default(ROUTE_VIA_VPN)
    assert iface == "utun8"
    assert gateway is None


def test_parse_route_through_wifi_yields_gateway():
    iface, gateway = parse_route_default(ROUTE_VIA_WIFI)
    assert iface == "en0"
    assert gateway == "192.168.0.1"


def test_parse_route_handles_empty_output():
    assert parse_route_default("") == (None, None)


def test_parse_scutil_finds_the_connected_vpn():
    assert parse_scutil_nc(SCUTIL_NC) == "PepperVPN"


def test_parse_scutil_returns_none_when_all_disconnected():
    text = SCUTIL_NC.replace("(Connected)     ", "(Disconnected)  ")
    assert parse_scutil_nc(text) is None


def test_parse_scutil_ignores_connected_modems():
    """PPP-модем от фитнес-браслета — не VPN, и путать его нельзя."""
    text = """Available network connection services in the current set (*=enabled):
* (Connected)      F9CF603C-0000-0000-0000-000000000000 PPP --> Healbe Gobe (BaseFW) "Healbe Gobe" [PPP:Modem]
"""
    assert parse_scutil_nc(text) is None


def test_virtual_and_tunnel_classification():
    assert is_virtual("utun8") and is_tunnel("utun8")
    assert is_virtual("lo0") and not is_tunnel("lo0")
    assert is_virtual("awdl0")
    assert not is_virtual("en0")
    assert not is_tunnel("en0")


def test_pick_physical_prefers_the_default_route_interface():
    candidates = [
        Interface("bridge0", "169.254.11.2"),
        Interface("en0", "192.168.0.248"),
    ]
    assert pick_physical(candidates, default_iface="en0").name == "en0"


def test_pick_physical_skips_link_local_addresses():
    """169.254.x — самоназначенный адрес, наружу через него не выйти."""
    candidates = [
        Interface("bridge0", "169.254.11.2"),
        Interface("en0", "192.168.0.248"),
    ]
    assert pick_physical(candidates, default_iface="utun8").name == "en0"


def test_pick_physical_prefers_real_nic_over_vm_bridge():
    """bridge100 — сеть для виртуалок: адрес маршрутизируемый, но наружу не ведёт."""
    candidates = [
        Interface("bridge100", "192.168.64.1"),
        Interface("en0", "192.168.0.248"),
    ]
    assert pick_physical(candidates, default_iface="utun8").name == "en0"


def test_pick_physical_returns_none_without_candidates():
    assert pick_physical([], default_iface=None) is None


def test_pick_physical_falls_back_to_link_local_if_nothing_else():
    candidates = [Interface("bridge0", "169.254.11.2")]
    assert pick_physical(candidates, default_iface=None).name == "bridge0"
