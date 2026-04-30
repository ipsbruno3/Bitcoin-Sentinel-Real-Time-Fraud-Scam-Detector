"""
Tests for sentinel.database — SQLite lightweight storage layer.
"""

import os
import tempfile

import pytest

from sentinel.database import Database


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path):
    """Return a fresh in-memory-equivalent Database using a temp file."""
    db_path = str(tmp_path / "test_sentinel.db")
    return Database(db_path=db_path)


# ---------------------------------------------------------------------------
# Address operations
# ---------------------------------------------------------------------------

class TestAddressOperations:
    def test_add_and_get_address(self, db):
        result = db.add_address(
            address="115p7UMMngoj1pMvkpHijcRdfJNXj6LrLn",
            risk_score=95,
            category="RANSOMWARE",
            cluster_id="wannacry_2017",
            notes="WannaCry wallet",
        )
        assert result is True

        record = db.get_address("115p7UMMngoj1pMvkpHijcRdfJNXj6LrLn")
        assert record is not None
        assert record["address"] == "115p7UMMngoj1pMvkpHijcRdfJNXj6LrLn"
        assert record["risk_score"] == 95
        assert record["category"] == "RANSOMWARE"
        assert record["cluster_id"] == "wannacry_2017"
        assert record["notes"] == "WannaCry wallet"
        assert record["tx_count"] == 0

    def test_get_nonexistent_address_returns_none(self, db):
        assert db.get_address("1nonexistentaddress") is None

    def test_address_exists(self, db):
        db.add_address("1A1zP1eP5QGefi2DMPTfTL5SLmv7Divfna", 50, "UNKNOWN")
        assert db.address_exists("1A1zP1eP5QGefi2DMPTfTL5SLmv7Divfna") is True
        assert db.address_exists("nothere") is False

    def test_upsert_updates_risk_score(self, db):
        db.add_address("1TestAddr", 50, "UNKNOWN")
        db.add_address("1TestAddr", 80, "FRAUD")
        record = db.get_address("1TestAddr")
        assert record["risk_score"] == 80
        assert record["category"] == "FRAUD"

    def test_update_address_seen(self, db):
        db.add_address("1SeenAddr", 60, "SCAM")
        db.update_address_seen("1SeenAddr")
        db.update_address_seen("1SeenAddr")
        record = db.get_address("1SeenAddr")
        assert record["tx_count"] == 2

    def test_list_addresses_filtered_by_category(self, db):
        db.add_address("1R1", 90, "RANSOMWARE")
        db.add_address("1S1", 85, "SCAM")
        db.add_address("1E1", 10, "EXCHANGE")

        results = db.list_addresses(category="RANSOMWARE")
        assert len(results) == 1
        assert results[0]["address"] == "1R1"

    def test_list_addresses_filtered_by_min_risk(self, db):
        db.add_address("1High", 90, "RANSOMWARE")
        db.add_address("1Low", 20, "UNKNOWN")

        results = db.list_addresses(min_risk=50)
        addresses = [r["address"] for r in results]
        assert "1High" in addresses
        assert "1Low" not in addresses


# ---------------------------------------------------------------------------
# Cluster operations
# ---------------------------------------------------------------------------

class TestClusterOperations:
    def test_add_and_get_cluster(self, db):
        result = db.add_cluster(
            cluster_id="test_cluster",
            name="Test Cluster",
            category="SCAM",
            description="A test cluster",
            confidence=80,
        )
        assert result is True

        record = db.get_cluster("test_cluster")
        assert record is not None
        assert record["id"] == "test_cluster"
        assert record["name"] == "Test Cluster"
        assert record["category"] == "SCAM"
        assert record["confidence"] == 80

    def test_get_nonexistent_cluster_returns_none(self, db):
        assert db.get_cluster("does_not_exist") is None

    def test_list_clusters(self, db):
        db.add_cluster("c1", "Cluster 1", "RANSOMWARE")
        db.add_cluster("c2", "Cluster 2", "DARKNET")
        clusters = db.list_clusters()
        ids = [c["id"] for c in clusters]
        assert "c1" in ids
        assert "c2" in ids

    def test_upsert_cluster_updates(self, db):
        db.add_cluster("c_update", "Old Name", "SCAM", confidence=50)
        db.add_cluster("c_update", "New Name", "FRAUD", confidence=90)
        record = db.get_cluster("c_update")
        assert record["name"] == "New Name"
        assert record["confidence"] == 90


# ---------------------------------------------------------------------------
# Alert operations
# ---------------------------------------------------------------------------

class TestAlertOperations:
    def test_record_and_list_alert(self, db):
        alert_id = db.record_alert(
            tx_hash="abc123",
            address="1TestAlert",
            risk_score=90,
            category="RANSOMWARE",
            cluster_id="test_cluster",
        )
        assert isinstance(alert_id, int)
        assert alert_id > 0

        alerts = db.list_alerts()
        assert len(alerts) == 1
        alert = alerts[0]
        assert alert["tx_hash"] == "abc123"
        assert alert["address"] == "1TestAlert"
        assert alert["risk_score"] == 90
        assert alert["category"] == "RANSOMWARE"

    def test_list_alerts_min_risk_filter(self, db):
        db.record_alert("tx1", "addr1", 90, "RANSOMWARE")
        db.record_alert("tx2", "addr2", 30, "UNKNOWN")
        alerts = db.list_alerts(min_risk=50)
        assert len(alerts) == 1
        assert alerts[0]["tx_hash"] == "tx1"

    def test_list_alerts_limit(self, db):
        for i in range(10):
            db.record_alert(f"tx{i}", f"addr{i}", 80, "SCAM")
        alerts = db.list_alerts(limit=5)
        assert len(alerts) == 5

    def test_alerts_ordered_newest_first(self, db):
        db.record_alert("tx_first", "addr1", 80, "SCAM")
        db.record_alert("tx_second", "addr2", 85, "FRAUD")
        alerts = db.list_alerts()
        # newest first
        assert alerts[0]["tx_hash"] == "tx_second"
