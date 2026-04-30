"""
Tests for sentinel.clusters — address clustering module.
"""

import json
import os
import tempfile

import pytest

from sentinel.clusters import AddressCluster, ClusterManager, CATEGORY_RISK_DEFAULTS
from sentinel.database import Database


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path):
    return Database(db_path=str(tmp_path / "test.db"))


@pytest.fixture
def mgr(db):
    return ClusterManager(db)


@pytest.fixture
def seed_file(tmp_path):
    """Write a minimal seed JSON file and return its path."""
    data = {
        "clusters": [
            {
                "id": "test_ransomware",
                "name": "Test Ransomware",
                "category": "RANSOMWARE",
                "description": "Test",
                "confidence": 99,
                "addresses": [
                    {"address": "1RansomAddr1", "risk_score": 95, "notes": "test"},
                    {"address": "1RansomAddr2", "risk_score": 90},
                ],
            },
            {
                "id": "test_exchange",
                "name": "Test Exchange",
                "category": "EXCHANGE",
                "confidence": 80,
                "addresses": [
                    {"address": "1ExchangeAddr1", "risk_score": 10},
                ],
            },
        ]
    }
    path = str(tmp_path / "seed.json")
    with open(path, "w") as f:
        json.dump(data, f)
    return path


# ---------------------------------------------------------------------------
# CATEGORY_RISK_DEFAULTS
# ---------------------------------------------------------------------------

class TestCategoryDefaults:
    def test_all_high_risk_categories_above_50(self):
        for cat in ("RANSOMWARE", "DARKNET", "SCAM", "FRAUD", "SANCTIONS"):
            assert CATEGORY_RISK_DEFAULTS[cat] >= 75

    def test_exchange_is_low_risk(self):
        assert CATEGORY_RISK_DEFAULTS["EXCHANGE"] <= 20

    def test_unknown_is_zero(self):
        assert CATEGORY_RISK_DEFAULTS["UNKNOWN"] == 0


# ---------------------------------------------------------------------------
# Loading from file
# ---------------------------------------------------------------------------

class TestLoadFromFile:
    def test_load_returns_total_address_count(self, mgr, seed_file):
        count = mgr.load_from_file(seed_file)
        assert count == 3

    def test_clusters_are_registered(self, mgr, seed_file):
        mgr.load_from_file(seed_file)
        assert mgr.cluster_count() == 2

    def test_addresses_are_indexed(self, mgr, seed_file):
        mgr.load_from_file(seed_file)
        assert mgr.address_count() == 3

    def test_missing_file_returns_zero(self, mgr, tmp_path):
        count = mgr.load_from_file(str(tmp_path / "nonexistent.json"))
        assert count == 0


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------

class TestLookup:
    def test_lookup_known_address(self, mgr, seed_file):
        mgr.load_from_file(seed_file)
        result = mgr.lookup("1RansomAddr1")
        assert result is not None
        assert result.address == "1RansomAddr1"
        assert result.risk_score == 95
        assert result.category == "RANSOMWARE"
        assert result.cluster.id == "test_ransomware"

    def test_lookup_unknown_address_returns_none(self, mgr, seed_file):
        mgr.load_from_file(seed_file)
        result = mgr.lookup("1UnknownAddr")
        assert result is None

    def test_lookup_exchange_address(self, mgr, seed_file):
        mgr.load_from_file(seed_file)
        result = mgr.lookup("1ExchangeAddr1")
        assert result is not None
        assert result.category == "EXCHANGE"
        assert result.risk_score == 10

    def test_lookup_falls_back_to_db(self, mgr, db, seed_file):
        """Addresses added directly to DB (by another process) are found."""
        db.add_address("1DBOnlyAddr", 80, "FRAUD", cluster_id=None)
        result = mgr.lookup("1DBOnlyAddr")
        assert result is not None
        assert result.risk_score == 80


# ---------------------------------------------------------------------------
# Runtime management
# ---------------------------------------------------------------------------

class TestRuntimeManagement:
    def test_register_cluster(self, mgr):
        cluster = AddressCluster(
            id="new_cluster",
            name="New Cluster",
            category="SCAM",
            addresses=["1NewAddr1", "1NewAddr2"],
        )
        mgr.register_cluster(cluster)
        assert mgr.cluster_count() == 1
        assert mgr.address_count() == 2
        assert mgr.lookup("1NewAddr1") is not None

    def test_add_address_to_existing_cluster(self, mgr):
        cluster = AddressCluster(
            id="dyn_cluster",
            name="Dynamic",
            category="RANSOMWARE",
            addresses=["1ExistingAddr"],
        )
        mgr.register_cluster(cluster)

        result = mgr.add_address_to_cluster(
            address="1NewDynAddr",
            cluster_id="dyn_cluster",
            risk_score=92,
            notes="dynamically discovered",
        )
        assert result is True
        lookup = mgr.lookup("1NewDynAddr")
        assert lookup is not None
        assert lookup.risk_score == 92

    def test_add_address_to_nonexistent_cluster_returns_false(self, mgr):
        result = mgr.add_address_to_cluster("1Addr", "does_not_exist")
        assert result is False

    def test_list_clusters(self, mgr, seed_file):
        mgr.load_from_file(seed_file)
        clusters = mgr.list_clusters()
        assert len(clusters) == 2
        ids = {c.id for c in clusters}
        assert "test_ransomware" in ids
        assert "test_exchange" in ids
