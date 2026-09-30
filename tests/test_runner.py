"""Поведение цикла опроса: гистерезис, расписание, реакция на смену сети.

Реальные пробы сюда не пускаются — вместо них подставляется коллектор,
который возвращает заранее заданные наборы.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lag_sonar import config
from lag_sonar.model import CoreState, Probe, RingState, Topology
from lag_sonar.runner import Monitor

LINKED = Topology(
    phys_iface="en0",
    phys_ip="192.168.0.248",
    gateway="192.168.0.1",
    default_iface="utun8",
    vpn_active=True,
    vpn_name="PepperVPN",
)

OTHER_WIFI = Topology(
    phys_iface="en0",
    phys_ip="10.0.0.5",
    gateway="10.0.0.1",
    default_iface="en0",
    vpn_active=False,
)


def healthy() -> dict[str, Probe]:
    return {
        "link": Probe("link", True),
        "gateway": Probe("gateway", True, 3.0),
        "direct": Probe("direct", True, 55.0),
        "tunnel": Probe("tunnel", True, 240.0),
        "dns": Probe("dns", True, 5.0),
        "claude_api": Probe("claude_api", True, 700.0, extra={"status": 401}),
        "claude_status": Probe("claude_status", True, extra={"indicator": "none"}),
    }


def claude_down() -> dict[str, Probe]:
    p = healthy()
    p["claude_api"] = Probe("claude_api", False, detail="таймаут")
    return p


def unplugged() -> dict[str, Probe]:
    return {
        "link": Probe("link", False, detail="нет интерфейса с IPv4"),
        "direct": Probe.skip("direct", "нет линка"),
        "tunnel": Probe("tunnel", False),
        "dns": Probe("dns", False),
        "claude_api": Probe("claude_api", False),
    }


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_monitor(sequence, topologies=None, clock=None):
    """Монитор, который на каждом тике берёт следующий набор проб."""
    clock = clock or FakeClock()
    state = {"i": 0}
    topologies = topologies or []

    def collector(topo, need_claude, need_status):
        i = min(state["i"], len(sequence) - 1)
        state["i"] += 1
        return dict(sequence[i])

    def snapshot():
        if not topologies:
            return LINKED
        return topologies[min(state["i"], len(topologies) - 1)]

    return Monitor(collector=collector, snapshot=snapshot, clock=clock), clock


# --- гистерезис -------------------------------------------------------------


def test_first_tick_publishes_immediately():
    """При старте ждать нечего — показываем то, что намерили."""
    monitor, _ = make_monitor([healthy()])
    verdict = monitor.tick()
    assert verdict.core is CoreState.OK


def test_single_bad_sample_does_not_flip_the_icon():
    """Один провал на флапающем канале — ещё не повод краснеть."""
    monitor, _ = make_monitor([healthy(), claude_down()])
    monitor.tick()
    verdict = monitor.tick()
    assert verdict.core is CoreState.OK


def test_two_bad_samples_in_a_row_flip_the_icon():
    monitor, _ = make_monitor([healthy(), claude_down(), claude_down()])
    monitor.tick()
    monitor.tick()
    verdict = monitor.tick()
    assert verdict.core is CoreState.DOWN


def test_recovery_also_requires_confirmation():
    monitor, _ = make_monitor(
        [claude_down(), claude_down(), healthy(), healthy()]
    )
    monitor.tick()
    monitor.tick()
    assert monitor.tick().core is CoreState.DOWN  # одного хорошего мало
    assert monitor.tick().core is CoreState.OK


def test_alternating_samples_never_flip():
    """Пила «плохо-хорошо-плохо» не должна дёргать иконку."""
    monitor, _ = make_monitor(
        [healthy(), claude_down(), healthy(), claude_down(), healthy()]
    )
    states = [monitor.tick().core for _ in range(5)]
    assert set(states) == {CoreState.OK}


def test_lost_link_is_published_without_delay():
    """Выключенный Wi-Fi — факт достоверный, ждать подтверждения нечего."""
    monitor, _ = make_monitor([healthy(), unplugged()])
    monitor.tick()
    assert monitor.tick().ring is RingState.NO_LINK


def test_network_change_resets_hysteresis():
    """Переезд на другую сеть: старые замеры больше ничего не значат."""
    monitor, _ = make_monitor(
        [healthy(), claude_down()], topologies=[LINKED, OTHER_WIFI]
    )
    monitor.tick()
    assert monitor.tick().core is CoreState.DOWN


# --- расписание -------------------------------------------------------------


def test_claude_is_probed_less_often_than_the_network():
    """Чужую инфраструктуру не долбим: сеть чаще, API реже."""
    calls = []
    clock = FakeClock()

    def collector(topo, need_claude, need_status):
        calls.append((need_claude, need_status))
        return healthy()

    monitor = Monitor(collector=collector, snapshot=lambda: LINKED, clock=clock)

    monitor.tick()
    clock.advance(config.NETWORK_INTERVAL_OK)
    monitor.tick()

    assert calls[0][0] is True  # на старте спрашиваем всё
    assert calls[1][0] is False  # 10 с спустя — только сеть


def test_claude_is_probed_again_after_its_interval():
    calls = []
    clock = FakeClock()

    def collector(topo, need_claude, need_status):
        calls.append(need_claude)
        return healthy()

    monitor = Monitor(collector=collector, snapshot=lambda: LINKED, clock=clock)
    monitor.tick()
    clock.advance(config.CLAUDE_INTERVAL_OK + 1)
    monitor.tick()

    assert calls[-1] is True


def test_degraded_state_shortens_the_interval():
    """Когда сломалось — опрашиваем чаще, чтобы быстрее увидеть починку."""
    monitor, _ = make_monitor([unplugged()])
    monitor.tick()
    assert monitor.interval == config.NETWORK_INTERVAL_DEGRADED


def test_healthy_state_uses_the_relaxed_interval():
    monitor, _ = make_monitor([healthy()])
    monitor.tick()
    assert monitor.interval == config.NETWORK_INTERVAL_OK


def test_cached_claude_result_is_reused_between_ticks():
    """Если API в этом тике не опрашивался, в вердикте остаётся прошлый ответ."""
    clock = FakeClock()

    def collector(topo, need_claude, need_status):
        p = healthy()
        if not need_claude:
            p.pop("claude_api")
            p.pop("claude_status")
        return p

    monitor = Monitor(collector=collector, snapshot=lambda: LINKED, clock=clock)
    monitor.tick()
    clock.advance(config.NETWORK_INTERVAL_OK)
    verdict = monitor.tick()

    assert verdict.core is CoreState.OK
    assert any(row.label == "Claude API" for row in verdict.details)


def test_collector_failure_does_not_break_the_loop():
    """Упавший сбор проб не должен ронять приложение."""
    clock = FakeClock()
    state = {"first": True}

    def collector(topo, need_claude, need_status):
        if state["first"]:
            state["first"] = False
            raise RuntimeError("что-то пошло не так")
        return healthy()

    monitor = Monitor(collector=collector, snapshot=lambda: LINKED, clock=clock)
    assert monitor.tick() is not None
    assert monitor.tick().core is CoreState.OK
