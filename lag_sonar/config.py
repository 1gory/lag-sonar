"""Все настраиваемые величины в одном месте.

Значения подобраны по замерам на живом канале 2026-09-30: через VPN ответ API
занимал 674–867 мс в норме и уходил в таймаут при деградации, поэтому пороги
щедрые — иначе иконка будет кричать на здоровой сети.
"""

from __future__ import annotations

import os
from pathlib import Path

# --- интервалы опроса, секунды ---------------------------------------------

# Часто: лаги Claude длятся 10–30 с (журнал 2026-10-02), и при опросе раз
# в 10–30 с значок замечал их, когда они уже заканчивались.
NETWORK_INTERVAL_OK = 2.0
NETWORK_INTERVAL_DEGRADED = 2.0

# Claude чуть реже сети: это запрос к чужому API, долбить его каждые 2 с
# без нужды незачем. Пока что-то не так — опрашиваем в темпе сети.
CLAUDE_INTERVAL_OK = 4.0
CLAUDE_INTERVAL_DEGRADED = 2.0

STATUS_INTERVAL = 300.0

# --- таймауты проб, секунды -------------------------------------------------

GATEWAY_TIMEOUT = 1.5
TLS_TIMEOUT = 4.0
DNS_TIMEOUT = 3.0
CLAUDE_TIMEOUT = 8.0
STATUS_TIMEOUT = 8.0

# --- пороги -----------------------------------------------------------------

CLAUDE_SLOW_MS = 1500.0

# Сколько подряд одинаковых вердиктов нужно, чтобы сменить показанное состояние.
# Канал флапает (см. дизайн, факт 6), без этого иконка мигает.
HYSTERESIS = 2

# --- цели проб --------------------------------------------------------------

# Два независимых якоря: один провайдер может резать конкретный резолвер,
# и тогда единственная цель дала бы ложную тревогу.
CONNECTIVITY_TARGETS: tuple[tuple[str, str], ...] = (
    ("1.1.1.1", "one.one.one.one"),
    ("8.8.8.8", "dns.google"),
)

CLAUDE_HOST = "api.anthropic.com"
CLAUDE_PATH = "/v1/models"
STATUS_URL = "https://status.anthropic.com/api/v2/status.json"

DNS_PROBE_NAME = CLAUDE_HOST

# --- прочее -----------------------------------------------------------------

USER_AGENT = "lag-sonar/0.1 (+menu-bar network indicator)"

LOG_PATH = Path(
    os.path.expanduser("~/Library/Logs/lag-sonar.log")
)

# Интерфейсы, которые никогда не считаются физическими.
VIRTUAL_IFACE_PREFIXES = (
    "lo",
    "utun",
    "ipsec",
    "ppp",
    "awdl",
    "llw",
    "gif",
    "stf",
    "anpi",
    "ap",
    "XHC",
)

# Интерфейсы, через которые может идти VPN-туннель.
TUNNEL_IFACE_PREFIXES = ("utun", "ipsec", "ppp", "tap", "tun")
