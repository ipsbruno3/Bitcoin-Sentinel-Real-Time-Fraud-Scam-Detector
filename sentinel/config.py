"""
Configuration settings for Bitcoin Sentinel.

Values can be overridden via environment variables with the ``SENTINEL_``
prefix (e.g. ``SENTINEL_DB_PATH``, ``SENTINEL_RISK_THRESHOLD``).
"""

import os
from dataclasses import dataclass, field
from typing import List

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _env(key: str, default: str) -> str:
    return os.environ.get(f"SENTINEL_{key}", default)


# ---------------------------------------------------------------------------
# Risk thresholds
# ---------------------------------------------------------------------------

RISK_LOW = 30
RISK_MEDIUM = 60
RISK_HIGH = 80

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = _env("DB_PATH", os.path.join(DATA_DIR, "sentinel.db"))
KNOWN_ADDRESSES_FILE = _env(
    "KNOWN_ADDRESSES_FILE",
    os.path.join(DATA_DIR, "known_addresses.json"),
)
WALLET_CACHE_FILE = _env(
    "WALLET_CACHE_FILE",
    os.path.join(DATA_DIR, "wallet_cache.json"),
)

# ---------------------------------------------------------------------------
# WebSocket / network
# ---------------------------------------------------------------------------

BTC_WS_URL = _env("BTC_WS_URL", "wss://ws.blockchain.info/inv")
WALLET_EXPLORER_BASE_URL = _env(
    "WALLET_EXPLORER_BASE_URL",
    "https://www.walletexplorer.com/api/1",
)
WALLET_EXPLORER_CALLER = _env("WALLET_EXPLORER_CALLER", "bitcoin-sentinel")

# How long to cache WalletExplorer responses (seconds)
WALLET_CACHE_TTL: int = int(_env("WALLET_CACHE_TTL", "86400"))

# ---------------------------------------------------------------------------
# Alert settings
# ---------------------------------------------------------------------------

# Minimum risk score required to emit an alert (0-100)
ALERT_THRESHOLD: int = int(_env("RISK_THRESHOLD", str(RISK_MEDIUM + 1)))

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_LEVEL = _env("LOG_LEVEL", "INFO")
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s — %(message)s"
