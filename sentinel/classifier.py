"""
Real-time transaction classification engine for Bitcoin Sentinel.

Classification pipeline for each incoming transaction
------------------------------------------------------
1. Extract all input/output Bitcoin addresses.
2. Look up every address in the cluster index (O(1) in-memory).
3. Query the ExchangeFilter for any address not already flagged — exchange
   addresses are marked low-risk and excluded from further analysis to keep
   false-positive rates minimal.
4. Compute a composite risk score from:
     - Cluster membership scores
     - Heuristics (mixing patterns, dust outputs, round-number amounts)
5. Emit a ``ClassificationResult`` describing the highest-risk addresses
   and the overall transaction risk level.

Risk levels
-----------
    CLEAN    (0–30)   — no suspicious signals
    LOW      (31–60)  — minor indicators, monitor
    MEDIUM   (61–80)  — significant indicators, review
    HIGH     (81–100) — confirmed suspicious / known malicious
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sentinel import config
from sentinel.clusters import ClusterManager, LookupResult
from sentinel.exchange_filter import ExchangeFilter

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RISK_CLEAN = "CLEAN"
RISK_LOW = "LOW"
RISK_MEDIUM = "MEDIUM"
RISK_HIGH = "HIGH"

# Satoshi thresholds
DUST_SATOSHIS = 546
BTC_ROUND_SATOSHIS = 100_000_000  # 1 BTC


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class AddressResult:
    """Classification result for a single address within a transaction."""

    address: str
    risk_score: int
    category: str
    cluster_id: Optional[str]
    cluster_name: Optional[str]
    is_exchange: bool
    notes: str = ""


@dataclass
class ClassificationResult:
    """Overall classification result for an entire transaction."""

    tx_hash: str
    risk_score: int           # 0-100 composite score
    risk_level: str           # CLEAN / LOW / MEDIUM / HIGH
    flagged_addresses: List[AddressResult] = field(default_factory=list)
    heuristic_flags: List[str] = field(default_factory=list)

    @property
    def is_suspicious(self) -> bool:
        return self.risk_score > config.RISK_LOW

    @property
    def should_alert(self) -> bool:
        return self.risk_score >= config.ALERT_THRESHOLD


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------

class TransactionClassifier:
    """
    Classifies a raw Bitcoin transaction object.

    Parameters
    ----------
    cluster_manager:
        Populated ``ClusterManager`` used for address lookups.
    exchange_filter:
        ``ExchangeFilter`` instance for exchange-wallet suppression.
    """

    def __init__(
        self,
        cluster_manager: ClusterManager,
        exchange_filter: ExchangeFilter,
    ) -> None:
        self._clusters = cluster_manager
        self._exchange = exchange_filter

    def set_exchange_filter(self, exchange_filter: ExchangeFilter) -> None:
        """Replace the exchange filter instance (e.g. to swap in a no-op filter)."""
        self._exchange = exchange_filter

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def classify(self, tx: Dict[str, Any]) -> ClassificationResult:
        """
        Classify a raw transaction dict (as received from the WebSocket feed).

        Expected keys (from blockchain.info WS API):
            ``hash``, ``inputs`` (list of ``{prev_out: {addr, value}}``),
            ``out``   (list of ``{addr, value}``).

        Returns a ``ClassificationResult``.
        """
        tx_hash = tx.get("hash", "unknown")
        inputs = tx.get("inputs", [])
        outputs = tx.get("out", [])

        all_addresses = _extract_addresses(inputs, outputs)

        flagged: List[AddressResult] = []
        heuristics: List[str] = []

        for addr in all_addresses:
            result = await self._classify_address(addr)
            if result.risk_score > 0 or result.is_exchange:
                flagged.append(result)

        # Heuristic: many small outputs (dust attack / mixing)
        if _has_dust_outputs(outputs):
            heuristics.append("DUST_OUTPUTS")

        # Heuristic: many equal-value outputs (coin-join / mixing)
        if _has_equal_outputs(outputs):
            heuristics.append("EQUAL_OUTPUTS_MIXING")

        # Heuristic: single round-number output with many inputs (consolidation)
        if _has_round_number_single_output(outputs):
            heuristics.append("ROUND_NUMBER_OUTPUT")

        # Heuristic: unusually high fan-out (1 input → many outputs)
        if _has_high_fanout(inputs, outputs):
            heuristics.append("HIGH_FANOUT")

        composite = _composite_score(flagged, heuristics)
        risk_level = _risk_level(composite)

        logger.debug(
            "tx=%s score=%d level=%s flagged=%d heuristics=%s",
            tx_hash,
            composite,
            risk_level,
            len(flagged),
            heuristics,
        )

        return ClassificationResult(
            tx_hash=tx_hash,
            risk_score=composite,
            risk_level=risk_level,
            flagged_addresses=flagged,
            heuristic_flags=heuristics,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _classify_address(self, address: str) -> AddressResult:
        # 1. Check cluster index first (fast path)
        lookup: Optional[LookupResult] = self._clusters.lookup(address)
        if lookup is not None:
            return AddressResult(
                address=address,
                risk_score=lookup.risk_score,
                category=lookup.category,
                cluster_id=lookup.cluster.id,
                cluster_name=lookup.cluster.name,
                is_exchange=lookup.category == "EXCHANGE",
            )

        # 2. Check WalletExplorer exchange filter (slow path, network call)
        is_exchange = await self._exchange.is_exchange(address)
        if is_exchange:
            label = await self._exchange.get_wallet_label(address)
            return AddressResult(
                address=address,
                risk_score=10,
                category="EXCHANGE",
                cluster_id=None,
                cluster_name=label,
                is_exchange=True,
            )

        # 3. Unknown / clean address
        return AddressResult(
            address=address,
            risk_score=0,
            category="UNKNOWN",
            cluster_id=None,
            cluster_name=None,
            is_exchange=False,
        )


# ---------------------------------------------------------------------------
# Address extraction helpers
# ---------------------------------------------------------------------------

def _extract_addresses(
    inputs: List[Dict[str, Any]],
    outputs: List[Dict[str, Any]],
) -> List[str]:
    """Return a deduplicated list of all addresses in inputs and outputs."""
    seen: set = set()
    result: List[str] = []
    for inp in inputs:
        addr = inp.get("prev_out", {}).get("addr")
        if addr and addr not in seen:
            seen.add(addr)
            result.append(addr)
    for out in outputs:
        addr = out.get("addr")
        if addr and addr not in seen:
            seen.add(addr)
            result.append(addr)
    return result


# ---------------------------------------------------------------------------
# Heuristic detectors
# ---------------------------------------------------------------------------

def _has_dust_outputs(outputs: List[Dict[str, Any]], threshold: int = 3) -> bool:
    """True if at least *threshold* outputs have dust-level values."""
    dust_count = sum(
        1 for o in outputs
        if isinstance(o.get("value"), int) and 0 < o["value"] <= DUST_SATOSHIS
    )
    return dust_count >= threshold


def _has_equal_outputs(
    outputs: List[Dict[str, Any]],
    min_outputs: int = 5,
) -> bool:
    """
    True if there are at least *min_outputs* outputs with the same value
    (classic CoinJoin / mixing signature).
    """
    if len(outputs) < min_outputs:
        return False
    values = [o.get("value") for o in outputs if isinstance(o.get("value"), int)]
    if not values:
        return False
    from collections import Counter
    freq = Counter(values)
    most_common_count = freq.most_common(1)[0][1]
    return most_common_count >= min_outputs


def _has_round_number_single_output(
    outputs: List[Dict[str, Any]],
) -> bool:
    """
    True if there is exactly one non-dust output and its value is a whole BTC
    (a pattern sometimes used to obscure the true change output).
    """
    non_dust = [
        o for o in outputs
        if isinstance(o.get("value"), int) and o["value"] > DUST_SATOSHIS
    ]
    if len(non_dust) != 1:
        return False
    value = non_dust[0]["value"]
    return value > 0 and value % BTC_ROUND_SATOSHIS == 0


def _has_high_fanout(
    inputs: List[Dict[str, Any]],
    outputs: List[Dict[str, Any]],
    ratio: int = 10,
) -> bool:
    """
    True if the output count is at least *ratio* times the input count
    (one-to-many payout pattern common in mixers).
    """
    if not inputs:
        return False
    return len(outputs) >= ratio * len(inputs)


# ---------------------------------------------------------------------------
# Score aggregation
# ---------------------------------------------------------------------------

def _composite_score(
    flagged: List[AddressResult],
    heuristics: List[str],
) -> int:
    """
    Compute a 0-100 composite risk score.

    Strategy:
      * Start from the highest individual address score.
      * Add a bonus for each heuristic flag (but cap at 100).
      * Exchange-only flags do not increase the score.
    """
    non_exchange_scores = [
        r.risk_score for r in flagged if not r.is_exchange and r.risk_score > 0
    ]
    base_score = max(non_exchange_scores) if non_exchange_scores else 0

    # Heuristic bonus: each flag adds up to 10 points
    heuristic_bonus = min(len(heuristics) * 10, 30)

    return min(base_score + heuristic_bonus, 100)


def _risk_level(score: int) -> str:
    if score <= config.RISK_LOW:
        return RISK_CLEAN
    if score <= config.RISK_MEDIUM:
        return RISK_LOW
    if score <= config.RISK_HIGH:
        return RISK_MEDIUM
    return RISK_HIGH
