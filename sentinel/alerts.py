"""
Alert formatting and output for Bitcoin Sentinel.

All alerts are written to stdout (and optionally to a log file) in a
structured, human-readable format.  The ``AlertManager`` also records every
alert in the Sentinel database for later review.

Alert levels (colour-coded when supported by the terminal)
----------------------------------------------------------
    CLEAN   — no action required
    LOW     — informational
    MEDIUM  — review recommended  (yellow)
    HIGH    — immediate action     (red)
"""

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sentinel import config
from sentinel.classifier import ClassificationResult
from sentinel.database import Database

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ANSI colours (disabled if stdout is not a TTY)
# ---------------------------------------------------------------------------

_USE_COLOUR = sys.stdout.isatty()

_RESET = "\033[0m" if _USE_COLOUR else ""
_BOLD  = "\033[1m"  if _USE_COLOUR else ""
_RED   = "\033[91m" if _USE_COLOUR else ""
_YELLOW= "\033[93m" if _USE_COLOUR else ""
_CYAN  = "\033[96m" if _USE_COLOUR else ""
_GREEN = "\033[92m" if _USE_COLOUR else ""
_DIM   = "\033[2m"  if _USE_COLOUR else ""


def _colour_for_level(level: str) -> str:
    return {
        "HIGH":   _RED,
        "MEDIUM": _YELLOW,
        "LOW":    _CYAN,
        "CLEAN":  _GREEN,
    }.get(level, "")


# ---------------------------------------------------------------------------
# AlertManager
# ---------------------------------------------------------------------------

class AlertManager:
    """
    Formats and emits Bitcoin Sentinel alerts.

    Parameters
    ----------
    db:
        ``Database`` instance used to persist alerts.
    threshold:
        Minimum risk score required to emit an alert (default from config).
    output_json:
        If True, emit machine-readable JSON lines instead of the human-readable
        format.  Useful for piping into SIEM / log aggregation systems.
    """

    def __init__(
        self,
        db: Database,
        threshold: int = config.ALERT_THRESHOLD,
        output_json: bool = False,
    ) -> None:
        self._db = db
        self._threshold = threshold
        self._output_json = output_json

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process(self, result: ClassificationResult) -> None:
        """
        Process a ``ClassificationResult``.  If the risk score meets the
        threshold, persist the alert and print it.
        """
        if result.risk_score < self._threshold:
            return

        for addr_result in result.flagged_addresses:
            if addr_result.is_exchange or addr_result.risk_score < self._threshold:
                continue
            alert_id = self._db.record_alert(
                tx_hash=result.tx_hash,
                address=addr_result.address,
                risk_score=result.risk_score,
                category=addr_result.category,
                cluster_id=addr_result.cluster_id,
            )
            logger.info(
                "Alert #%d: tx=%s addr=%s score=%d category=%s",
                alert_id,
                result.tx_hash,
                addr_result.address,
                result.risk_score,
                addr_result.category,
            )

        self._emit(result)

    # ------------------------------------------------------------------
    # Formatting
    # ------------------------------------------------------------------

    def _emit(self, result: ClassificationResult) -> None:
        if self._output_json:
            self._emit_json(result)
        else:
            self._emit_human(result)

    def _emit_json(self, result: ClassificationResult) -> None:
        record: Dict[str, Any] = {
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "tx_hash": result.tx_hash,
            "risk_score": result.risk_score,
            "risk_level": result.risk_level,
            "heuristic_flags": result.heuristic_flags,
            "flagged_addresses": [
                {
                    "address": a.address,
                    "risk_score": a.risk_score,
                    "category": a.category,
                    "cluster_id": a.cluster_id,
                    "cluster_name": a.cluster_name,
                    "is_exchange": a.is_exchange,
                }
                for a in result.flagged_addresses
                if not a.is_exchange
            ],
        }
        print(json.dumps(record, ensure_ascii=False), flush=True)

    def _emit_human(self, result: ClassificationResult) -> None:
        colour = _colour_for_level(result.risk_level)
        timestamp = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        header = (
            f"{colour}{_BOLD}[{result.risk_level}]{_RESET} "
            f"{_BOLD}Bitcoin Sentinel Alert{_RESET} — "
            f"{timestamp}"
        )
        print(header)
        print(f"  {'TX Hash:':<18} {result.tx_hash}")
        print(f"  {'Risk Score:':<18} {colour}{result.risk_score}/100{_RESET}")

        if result.heuristic_flags:
            print(f"  {'Heuristics:':<18} {', '.join(result.heuristic_flags)}")

        suspicious = [a for a in result.flagged_addresses if not a.is_exchange]
        if suspicious:
            print(f"  {'Flagged Addresses:'}")
            for addr in suspicious:
                cluster_info = (
                    f" [{addr.cluster_name or addr.cluster_id}]"
                    if addr.cluster_id
                    else ""
                )
                print(
                    f"    {colour}{addr.address}{_RESET}"
                    f"  score={addr.risk_score}  category={addr.category}"
                    f"{cluster_info}"
                )

        print(_DIM + "─" * 72 + _RESET, flush=True)
