"""
Tests for sentinel.classifier — transaction classification engine.
"""

import pytest
import pytest_asyncio

from sentinel.classifier import (
    TransactionClassifier,
    ClassificationResult,
    _extract_addresses,
    _has_dust_outputs,
    _has_equal_outputs,
    _has_high_fanout,
    _has_round_number_single_output,
    _composite_score,
    _risk_level,
    RISK_CLEAN,
    RISK_LOW,
    RISK_MEDIUM,
    RISK_HIGH,
    AddressResult,
)
from sentinel.clusters import AddressCluster, ClusterManager
from sentinel.database import Database
from sentinel.exchange_filter import ExchangeFilter


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

class _FakeExchangeFilter(ExchangeFilter):
    """Exchange filter stub: marks addresses ending in 'X' as exchange."""

    def __init__(self, exchange_addresses=None):
        self._exchange_addresses = set(exchange_addresses or [])

    async def get_wallet_label(self, address):
        if address in self._exchange_addresses:
            return "FakeExchange"
        return None

    async def is_exchange(self, address):
        return address in self._exchange_addresses

    async def close(self):
        pass


@pytest.fixture
def db(tmp_path):
    return Database(db_path=str(tmp_path / "test.db"))


@pytest.fixture
def cluster_mgr(db):
    mgr = ClusterManager(db)
    # Register a ransomware cluster with one known address
    mgr.register_cluster(
        AddressCluster(
            id="fake_ransomware",
            name="Fake Ransomware",
            category="RANSOMWARE",
            confidence=99,
            addresses=["1RansomAddr"],
        )
    )
    # Register a mixer cluster
    mgr.register_cluster(
        AddressCluster(
            id="fake_mixer",
            name="Fake Mixer",
            category="MIXER",
            confidence=90,
            addresses=["1MixerAddr"],
        )
    )
    return mgr


@pytest.fixture
def exchange_filter():
    return _FakeExchangeFilter(exchange_addresses={"1ExchangeAddr"})


@pytest.fixture
def classifier(cluster_mgr, exchange_filter):
    return TransactionClassifier(
        cluster_manager=cluster_mgr,
        exchange_filter=exchange_filter,
    )


# ---------------------------------------------------------------------------
# Address extraction
# ---------------------------------------------------------------------------

class TestExtractAddresses:
    def test_extracts_input_and_output_addresses(self):
        inputs = [{"prev_out": {"addr": "addr_in", "value": 1000}}]
        outputs = [{"addr": "addr_out", "value": 900}]
        addresses = _extract_addresses(inputs, outputs)
        assert "addr_in" in addresses
        assert "addr_out" in addresses

    def test_deduplicates_addresses(self):
        inputs = [{"prev_out": {"addr": "shared", "value": 1000}}]
        outputs = [{"addr": "shared", "value": 900}]
        addresses = _extract_addresses(inputs, outputs)
        assert addresses.count("shared") == 1

    def test_handles_missing_addr_gracefully(self):
        inputs = [{"prev_out": {"value": 1000}}]  # no addr
        outputs = [{"value": 900}]  # no addr
        addresses = _extract_addresses(inputs, outputs)
        assert addresses == []


# ---------------------------------------------------------------------------
# Heuristic detectors
# ---------------------------------------------------------------------------

class TestHeuristics:
    def test_dust_outputs_detected(self):
        outputs = [{"value": 546}, {"value": 300}, {"value": 100}]
        assert _has_dust_outputs(outputs, threshold=3) is True

    def test_dust_outputs_below_threshold(self):
        outputs = [{"value": 546}, {"value": 1000000}]
        assert _has_dust_outputs(outputs, threshold=3) is False

    def test_equal_outputs_mixing(self):
        outputs = [{"value": 100000}] * 5
        assert _has_equal_outputs(outputs, min_outputs=5) is True

    def test_equal_outputs_not_enough(self):
        outputs = [{"value": 100000}] * 4
        assert _has_equal_outputs(outputs, min_outputs=5) is False

    def test_round_number_single_output(self):
        outputs = [{"value": 100_000_000}, {"value": 546}]  # 1 BTC + dust change
        assert _has_round_number_single_output(outputs) is True

    def test_round_number_two_non_dust_outputs(self):
        outputs = [{"value": 100_000_000}, {"value": 50_000_000}]
        assert _has_round_number_single_output(outputs) is False

    def test_high_fanout(self):
        inputs = [{"prev_out": {"addr": "in", "value": 1000}}]
        outputs = [{"addr": f"out{i}", "value": 90} for i in range(10)]
        assert _has_high_fanout(inputs, outputs, ratio=10) is True

    def test_no_high_fanout(self):
        inputs = [{"prev_out": {"addr": "in", "value": 1000}}] * 2
        outputs = [{"addr": "out", "value": 900}]
        assert _has_high_fanout(inputs, outputs, ratio=10) is False


# ---------------------------------------------------------------------------
# Risk level and composite score
# ---------------------------------------------------------------------------

class TestRiskLevelAndScore:
    def test_risk_level_clean(self):
        assert _risk_level(0) == RISK_CLEAN
        assert _risk_level(30) == RISK_CLEAN

    def test_risk_level_low(self):
        assert _risk_level(31) == RISK_LOW
        assert _risk_level(60) == RISK_LOW

    def test_risk_level_medium(self):
        assert _risk_level(61) == RISK_MEDIUM
        assert _risk_level(80) == RISK_MEDIUM

    def test_risk_level_high(self):
        assert _risk_level(81) == RISK_HIGH
        assert _risk_level(100) == RISK_HIGH

    def test_composite_score_uses_max_address_score(self):
        flagged = [
            AddressResult("a1", 90, "RANSOMWARE", "c1", "X", False),
            AddressResult("a2", 50, "SCAM", "c2", "Y", False),
        ]
        assert _composite_score(flagged, []) == 90

    def test_composite_score_ignores_exchange(self):
        flagged = [
            AddressResult("a1", 10, "EXCHANGE", None, "Binance", True),
        ]
        assert _composite_score(flagged, []) == 0

    def test_composite_score_adds_heuristic_bonus(self):
        flagged = [AddressResult("a1", 70, "SCAM", "c1", "X", False)]
        score = _composite_score(flagged, ["DUST_OUTPUTS", "EQUAL_OUTPUTS_MIXING"])
        assert score == min(70 + 20, 100)

    def test_composite_score_capped_at_100(self):
        flagged = [AddressResult("a1", 95, "RANSOMWARE", "c1", "X", False)]
        score = _composite_score(
            flagged,
            ["DUST_OUTPUTS", "EQUAL_OUTPUTS_MIXING", "HIGH_FANOUT", "ROUND_NUMBER_OUTPUT"],
        )
        assert score == 100


# ---------------------------------------------------------------------------
# Full classifier (async)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestTransactionClassifier:
    async def test_clean_transaction_no_alert(self, classifier):
        tx = {
            "hash": "clean_tx",
            "inputs": [{"prev_out": {"addr": "1CleanAddr", "value": 1000000}}],
            "out": [{"addr": "1AnotherClean", "value": 990000}],
        }
        result = await classifier.classify(tx)
        assert result.tx_hash == "clean_tx"
        assert result.risk_score == 0
        assert result.risk_level == RISK_CLEAN
        assert result.should_alert is False

    async def test_ransomware_address_triggers_high_risk(self, classifier):
        tx = {
            "hash": "ransom_tx",
            "inputs": [{"prev_out": {"addr": "1SenderAddr", "value": 5000000}}],
            "out": [{"addr": "1RansomAddr", "value": 4990000}],
        }
        result = await classifier.classify(tx)
        assert result.risk_score >= 80
        assert result.risk_level in (RISK_MEDIUM, RISK_HIGH)
        flagged_addrs = [a.address for a in result.flagged_addresses]
        assert "1RansomAddr" in flagged_addrs

    async def test_exchange_address_does_not_inflate_score(self, classifier):
        tx = {
            "hash": "exchange_tx",
            "inputs": [{"prev_out": {"addr": "1SomeAddr", "value": 1000000}}],
            "out": [{"addr": "1ExchangeAddr", "value": 990000}],
        }
        result = await classifier.classify(tx)
        # Exchange address should not drive risk score up
        assert result.risk_score <= 30

    async def test_missing_hash_uses_unknown(self, classifier):
        tx = {
            "inputs": [],
            "out": [],
        }
        result = await classifier.classify(tx)
        assert result.tx_hash == "unknown"

    async def test_mixing_heuristics_detected(self, classifier):
        # A transaction with many equal-value outputs (CoinJoin pattern)
        outputs = [{"addr": f"1Out{i}", "value": 100000} for i in range(10)]
        tx = {
            "hash": "mix_tx",
            "inputs": [{"prev_out": {"addr": "1InAddr", "value": 1_000_000}}],
            "out": outputs,
        }
        result = await classifier.classify(tx)
        assert "EQUAL_OUTPUTS_MIXING" in result.heuristic_flags
        assert "HIGH_FANOUT" in result.heuristic_flags

    async def test_flagged_addresses_contain_mixer(self, classifier):
        tx = {
            "hash": "mixer_tx",
            "inputs": [{"prev_out": {"addr": "1SourceAddr", "value": 5000000}}],
            "out": [{"addr": "1MixerAddr", "value": 4990000}],
        }
        result = await classifier.classify(tx)
        flagged_addrs = [a.address for a in result.flagged_addresses]
        assert "1MixerAddr" in flagged_addrs
