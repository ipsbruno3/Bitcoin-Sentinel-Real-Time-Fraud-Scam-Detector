"""
Exchange wallet intelligence for Bitcoin Sentinel.

Integrates with WalletExplorer to identify whether a Bitcoin address belongs
to a known exchange or large custodial service.  Exchange addresses generate a
lot of on-chain activity but are not inherently suspicious — filtering them out
drastically reduces false positives.

How it works
------------
1. For every address seen in a transaction we query WalletExplorer's
   ``address-lookup`` endpoint.
2. Responses are cached locally (JSON file, TTL-controlled) to minimise
   network traffic and respect WalletExplorer's rate limits.
3. A returned wallet label that matches our ``EXCHANGE_PATTERNS`` list is
   classified as ``EXCHANGE`` with a low risk score (≤10).
4. If WalletExplorer is unavailable the filter gracefully degrades — it
   returns ``None`` so the classifier can fall back to other signals.
"""

import asyncio
import json
import logging
import os
import re
import time
from typing import Dict, Optional, Tuple

import aiohttp

from sentinel import config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Patterns that identify exchange / custodial-service wallet labels
# ---------------------------------------------------------------------------

EXCHANGE_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"binance",
        r"coinbase",
        r"kraken",
        r"bitfinex",
        r"huobi",
        r"okex|okx",
        r"bitstamp",
        r"gemini",
        r"kucoin",
        r"bybit",
        r"bitmex",
        r"bittrex",
        r"poloniex",
        r"ftx",
        r"gate\.io",
        r"crypto\.com",
        r"blockchain\.com",
        r"cex\.io",
        r"luno",
        r"paxos",
        r"itbit",
        r"liquid",
        r"bitso",
        r"upbit",
        r"bithumb",
        r"coinone",
        r"korbit",
    ]
]


def _is_exchange_label(label: str) -> bool:
    """Return True if *label* matches any known exchange pattern."""
    return any(pat.search(label) for pat in EXCHANGE_PATTERNS)


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

class _WalletCache:
    """Simple on-disk JSON cache for WalletExplorer responses."""

    def __init__(self, path: str, ttl: int) -> None:
        self._path = path
        self._ttl = ttl
        self._data: Dict[str, Tuple[float, Optional[str]]] = {}
        self._load()

    def _load(self) -> None:
        if os.path.isfile(self._path):
            try:
                with open(self._path, encoding="utf-8") as fh:
                    self._data = json.load(fh)
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Wallet cache load error: %s", exc)
                self._data = {}

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        try:
            with open(self._path, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh)
        except OSError as exc:
            logger.warning("Wallet cache save error: %s", exc)

    def get(self, address: str) -> Optional[Optional[str]]:
        """Return cached wallet label, or *sentinel* ``...`` if not cached."""
        entry = self._data.get(address)
        if entry is None:
            return ...  # type: ignore[return-value]  # not cached
        ts, label = entry
        if time.time() - ts > self._ttl:
            return ...  # type: ignore[return-value]  # expired
        return label  # may be None (= "not an exchange")

    def set(self, address: str, label: Optional[str]) -> None:
        self._data[address] = (time.time(), label)
        self._save()


# ---------------------------------------------------------------------------
# ExchangeFilter
# ---------------------------------------------------------------------------

class ExchangeFilter:
    """
    Queries WalletExplorer to decide whether a Bitcoin address belongs to a
    known exchange, caching responses locally.

    Parameters
    ----------
    session:
        An optional ``aiohttp.ClientSession``.  If not supplied one is created
        on first use.
    """

    def __init__(
        self,
        session: Optional[aiohttp.ClientSession] = None,
        cache_path: str = config.WALLET_CACHE_FILE,
        cache_ttl: int = config.WALLET_CACHE_TTL,
        base_url: str = config.WALLET_EXPLORER_BASE_URL,
        caller: str = config.WALLET_EXPLORER_CALLER,
    ) -> None:
        self._session = session
        self._cache = _WalletCache(cache_path, cache_ttl)
        self._base_url = base_url.rstrip("/")
        self._caller = caller
        self._own_session = session is None

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10)
            )
        return self._session

    async def close(self) -> None:
        if self._own_session and self._session and not self._session.closed:
            await self._session.close()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_wallet_label(self, address: str) -> Optional[str]:
        """
        Return the WalletExplorer wallet label for *address*, or ``None`` if
        the address is not associated with a known wallet.

        Uses the local cache.  Network errors are caught and logged — the
        method degrades gracefully by returning ``None``.
        """
        cached = self._cache.get(address)
        if cached is not ...:  # type: ignore[comparison-overlap]
            return cached  # type: ignore[return-value]

        label = await self._query_walletexplorer(address)
        self._cache.set(address, label)
        return label

    async def is_exchange(self, address: str) -> bool:
        """Return True if *address* belongs to a known exchange wallet."""
        label = await self.get_wallet_label(address)
        if label is None:
            return False
        return _is_exchange_label(label)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _query_walletexplorer(self, address: str) -> Optional[str]:
        url = f"{self._base_url}/address"
        params = {"address": address, "caller": self._caller}
        try:
            session = await self._get_session()
            async with session.get(url, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    return data.get("wallet", {}).get("label") or None
                elif resp.status == 404:
                    return None
                else:
                    logger.warning(
                        "WalletExplorer returned HTTP %s for %s",
                        resp.status,
                        address,
                    )
                    return None
        except asyncio.TimeoutError:
            logger.debug("WalletExplorer timeout for %s", address)
            return None
        except aiohttp.ClientError as exc:
            logger.debug("WalletExplorer request error for %s: %s", address, exc)
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Unexpected error querying WalletExplorer for %s: %s", address, exc
            )
            return None
