"""Цикл опроса: что и когда измерять, и когда верить результату.

Отвечает на три вопроса, которые не место решать ни пробам, ни диагностике:
какие пробы пора запускать, сколько ждать подтверждения перед сменой иконки
и как часто повторять цикл.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from . import config, netinfo, probes as probe_module
from .diagnosis import diagnose
from .model import CoreState, Probe, RingState, Topology, Verdict

log = logging.getLogger("lag_sonar.runner")

# Состояния, при которых опрашиваем чаще: человек ждёт, когда починится.
DEGRADED_RINGS = frozenset(
    {RingState.NO_LINK, RingState.ISP_DOWN, RingState.VPN_DOWN, RingState.DNS_DOWN}
)
DEGRADED_CORES = frozenset(
    {CoreState.DOWN, CoreState.SLOW, CoreState.BLOCKED, CoreState.INCIDENT}
)

# Показывается до первого удачного цикла и когда измерение не состоялось.
UNMEASURED = Verdict(
    ring=RingState.UNKNOWN,
    core=CoreState.UNKNOWN,
    headline="Состояние ещё не измерено",
)


def collect(topo: Topology, need_claude: bool, need_status: bool) -> dict[str, Probe]:
    """Запустить пробы параллельно.

    Каждая проба уходит в свой поток: суммарное время цикла определяется самой
    медленной, а не суммой таймаутов. В главном потоке не выполняется ничего.
    """
    tasks: dict[str, Callable[[], Probe]] = {
        "link": lambda: probe_module.probe_link(topo),
        "gateway": lambda: probe_module.probe_gateway(topo),
        "direct": lambda: probe_module.probe_direct(topo),
        "tunnel": lambda: probe_module.probe_tunnel(topo),
        "dns": probe_module.probe_dns,
    }
    if need_claude:
        tasks["claude_api"] = probe_module.probe_claude_api
    if need_status:
        tasks["claude_status"] = probe_module.probe_claude_status

    results: dict[str, Probe] = {}
    with ThreadPoolExecutor(max_workers=len(tasks), thread_name_prefix="probe") as pool:
        futures = {name: pool.submit(fn) for name, fn in tasks.items()}
        for name, future in futures.items():
            try:
                results[name] = future.result()
            except Exception as exc:  # noqa: BLE001
                log.warning("проба %s упала: %r", name, exc)
                results[name] = Probe(name, False, detail="сбой пробы")
    return results


class Monitor:
    """Состояние опроса между тиками.

    Хранит кэш редких проб, счётчик подтверждений для гистерезиса и момент
    последнего опроса каждой группы.
    """

    def __init__(
        self,
        collector: Callable[[Topology, bool, bool], dict[str, Probe]] = collect,
        snapshot: Callable[[], Topology] = netinfo.snapshot,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._collect = collector
        self._snapshot = snapshot
        self._clock = clock

        self._cache: dict[str, Probe] = {}
        self._last_claude: float | None = None
        self._last_status: float | None = None

        self._topology: Topology | None = None
        self._published: Verdict | None = None
        self._pending: tuple[RingState, CoreState] | None = None
        self._pending_count = 0

    # --- расписание ---------------------------------------------------------

    @property
    def interval(self) -> float:
        """Через сколько секунд имеет смысл повторить цикл."""
        if self._published is None:
            return config.NETWORK_INTERVAL_OK
        degraded = (
            self._published.ring in DEGRADED_RINGS
            or self._published.core in DEGRADED_CORES
        )
        return (
            config.NETWORK_INTERVAL_DEGRADED if degraded else config.NETWORK_INTERVAL_OK
        )

    def _due(self, last: float | None, ok_period: float, degraded_period: float) -> bool:
        if last is None:
            return True
        degraded = self._published is not None and (
            self._published.ring in DEGRADED_RINGS
            or self._published.core in DEGRADED_CORES
        )
        period = degraded_period if degraded else ok_period
        return self._clock() - last >= period

    # --- цикл ---------------------------------------------------------------

    def tick(self) -> Verdict:
        """Один цикл измерения. Возвращает вердикт, который следует показать."""
        try:
            topo = self._snapshot()
        except Exception as exc:  # noqa: BLE001
            log.warning("не удалось снять топологию: %r", exc)
            topo = self._topology or Topology()

        if not topo.same_shape(self._topology):
            # Сеть сменилась — прошлые замеры больше ни о чём не говорят.
            self._reset_hysteresis()
            self._cache.clear()
            self._last_claude = None
            self._last_status = None
        self._topology = topo

        need_claude = self._due(
            self._last_claude, config.CLAUDE_INTERVAL_OK, config.CLAUDE_INTERVAL_DEGRADED
        )
        need_status = self._due(self._last_status, config.STATUS_INTERVAL, config.STATUS_INTERVAL)

        try:
            fresh = self._collect(topo, need_claude, need_status)
        except Exception as exc:  # noqa: BLE001
            # Несостоявшееся измерение — не то же самое, что измеренная поломка.
            # Показывать «сети нет» на основании отсутствия данных нельзя.
            log.warning("сбор проб упал: %r", exc)
            return self._published or UNMEASURED

        now = self._clock()
        if "claude_api" in fresh:
            self._last_claude = now
        if "claude_status" in fresh:
            self._last_status = now

        merged = dict(self._cache)
        merged.update(fresh)
        # Кэшируем только редкие пробы: сетевые всегда свежие.
        for name in ("claude_api", "claude_status"):
            if name in fresh:
                self._cache[name] = fresh[name]

        verdict = diagnose(merged, topo)
        return self._publish(verdict)

    # --- гистерезис ---------------------------------------------------------

    def _reset_hysteresis(self) -> None:
        self._pending = None
        self._pending_count = 0
        self._published = None

    def _publish(self, verdict: Verdict) -> Verdict:
        """Пропустить вердикт через гистерезис.

        Смена показанного состояния требует подтверждения, иначе на канале
        с разбросом от 450 мс до таймаута иконка мигала бы непрерывно.
        Исключение — пропавший линк: этот факт достоверен сразу.
        """
        shape = (verdict.ring, verdict.core)

        if self._published is None or verdict.ring is RingState.NO_LINK:
            self._published = verdict
            self._pending = None
            self._pending_count = 0
            return verdict

        if shape == (self._published.ring, self._published.core):
            # Подтверждение текущего состояния: обновляем цифры в меню.
            self._published = verdict
            self._pending = None
            self._pending_count = 0
            return verdict

        if shape == self._pending:
            self._pending_count += 1
        else:
            self._pending = shape
            self._pending_count = 1

        if self._pending_count >= config.HYSTERESIS:
            self._published = verdict
            self._pending = None
            self._pending_count = 0

        return self._published
