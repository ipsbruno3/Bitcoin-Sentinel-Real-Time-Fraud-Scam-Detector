"""
WebSocket monitor — real-time Bitcoin transaction feed.

Connects to the Blockchain.com WebSocket API (``wss://ws.blockchain.info/inv``)
and processes every unconfirmed transaction as it propagates through the
network.

Reconnection strategy
---------------------
The monitor implements exponential back-off with jitter on connection failures
so it recovers gracefully from transient network issues without hammering the
server.

Usage
-----
    import asyncio
    from sentinel.monitor import Monitor

    monitor = Monitor(classifier, alert_manager)
    asyncio.run(monitor.run())
"""

import asyncio
import json
import logging
import random
from typing import Any, Callable, Coroutine, Dict, Optional

import websockets
from websockets.exceptions import ConnectionClosed

from sentinel import config
from sentinel.alerts import AlertManager
from sentinel.classifier import TransactionClassifier

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUBSCRIBE_MSG = json.dumps({"op": "unconfirmed_sub"})
PING_MSG = json.dumps({"op": "ping"})

BACKOFF_BASE = 2.0     # seconds
BACKOFF_MAX = 300.0    # 5 minutes ceiling
PING_INTERVAL = 30.0   # seconds between keep-alive pings


# ---------------------------------------------------------------------------
# Monitor
# ---------------------------------------------------------------------------

class Monitor:
    """
    Real-time Bitcoin transaction monitor.

    Parameters
    ----------
    classifier:
        ``TransactionClassifier`` instance.
    alert_manager:
        ``AlertManager`` instance.
    ws_url:
        WebSocket endpoint (default: Blockchain.com).
    on_alert:
        Optional async callback invoked for every alert-worthy result.
        Receives a ``ClassificationResult``.
    """

    def __init__(
        self,
        classifier: TransactionClassifier,
        alert_manager: AlertManager,
        ws_url: str = config.BTC_WS_URL,
        on_alert: Optional[
            Callable[..., Coroutine[Any, Any, None]]
        ] = None,
    ) -> None:
        self._classifier = classifier
        self._alert_manager = alert_manager
        self._ws_url = ws_url
        self._on_alert = on_alert
        self._running = False
        self._tx_count = 0
        self._alert_count = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """
        Start the monitor loop.  Runs indefinitely until ``stop()`` is called
        or the process is interrupted.
        """
        self._running = True
        attempt = 0
        logger.info("Bitcoin Sentinel monitor starting — feed: %s", self._ws_url)

        while self._running:
            try:
                await self._connect_and_listen()
                attempt = 0  # reset on clean disconnect
            except asyncio.CancelledError:
                logger.info("Monitor cancelled.")
                break
            except Exception as exc:  # noqa: BLE001
                if not self._running:
                    break
                wait = _backoff(attempt)
                logger.warning(
                    "WebSocket error (attempt %d): %s — retrying in %.1fs",
                    attempt,
                    exc,
                    wait,
                )
                await asyncio.sleep(wait)
                attempt += 1

        logger.info(
            "Monitor stopped. Processed %d transactions, emitted %d alerts.",
            self._tx_count,
            self._alert_count,
        )

    def stop(self) -> None:
        """Signal the monitor to stop after the current message."""
        self._running = False
        logger.info("Monitor stop requested.")

    @property
    def tx_count(self) -> int:
        return self._tx_count

    @property
    def alert_count(self) -> int:
        return self._alert_count

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _connect_and_listen(self) -> None:
        logger.info("Connecting to %s …", self._ws_url)
        async with websockets.connect(
            self._ws_url,
            ping_interval=None,  # we send our own pings
            open_timeout=20,
            close_timeout=10,
        ) as ws:
            logger.info("Connected. Subscribing to unconfirmed transactions …")
            await ws.send(SUBSCRIBE_MSG)

            ping_task = asyncio.create_task(self._ping_loop(ws))
            try:
                async for raw_msg in ws:
                    if not self._running:
                        break
                    await self._handle_message(raw_msg)
            finally:
                ping_task.cancel()
                try:
                    await ping_task
                except asyncio.CancelledError:
                    pass

    async def _ping_loop(self, ws: Any) -> None:
        """Send periodic pings to keep the connection alive."""
        while True:
            await asyncio.sleep(PING_INTERVAL)
            try:
                await ws.send(PING_MSG)
                logger.debug("Ping sent.")
            except ConnectionClosed:
                break

    async def _handle_message(self, raw_msg: str) -> None:
        try:
            msg = json.loads(raw_msg)
        except json.JSONDecodeError as exc:
            logger.debug("JSON decode error: %s", exc)
            return

        op = msg.get("op")

        if op == "utx":
            tx: Dict[str, Any] = msg.get("x", {})
            self._tx_count += 1
            result = await self._classifier.classify(tx)

            if result.should_alert:
                self._alert_count += 1
                self._alert_manager.process(result)
                if self._on_alert:
                    await self._on_alert(result)
            else:
                # Still pass to alert_manager so it can decide (respects its
                # own threshold setting, which may differ from the classifier).
                self._alert_manager.process(result)

        elif op == "pong":
            logger.debug("Pong received.")

        elif op == "status":
            logger.debug("Status: %s", msg)

        else:
            logger.debug("Unhandled op=%s", op)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _backoff(attempt: int) -> float:
    """Exponential back-off with ±25 % jitter, capped at BACKOFF_MAX."""
    base = min(BACKOFF_BASE * (2 ** attempt), BACKOFF_MAX)
    jitter = base * 0.25 * (2 * random.random() - 1)
    return max(1.0, base + jitter)
