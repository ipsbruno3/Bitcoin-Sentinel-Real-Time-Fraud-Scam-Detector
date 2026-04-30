"""
Address clustering module for Bitcoin Sentinel.

A *cluster* is a named group of Bitcoin addresses that belong to the same
entity (e.g. a ransomware family, a specific darknet market, a mixing
service).  By tagging every member of a cluster with the same ``cluster_id``
we can:

  * Generate cluster-level alerts instead of individual address alerts.
  * Aggregate intelligence: if a single new address is linked to a known
    cluster, it instantly inherits the cluster's risk profile.
  * Maintain a lightweight footprint — only pivot addresses are stored.

Usage
-----
    from sentinel.clusters import ClusterManager, AddressCluster

    mgr = ClusterManager(db)
    mgr.load_from_file("data/known_addresses.json")

    result = mgr.lookup("1A1zP1eP5QGefi2DMPTfTL5SLmv7Divf...")
    if result:
        print(result.cluster.name, result.risk_score)
"""

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from sentinel import config
from sentinel.database import Database

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Risk score defaults per category
# ---------------------------------------------------------------------------

CATEGORY_RISK_DEFAULTS: Dict[str, int] = {
    "RANSOMWARE": 95,
    "DARKNET": 90,
    "SCAM": 85,
    "FRAUD": 85,
    "MIXER": 75,
    "SANCTIONS": 100,
    "EXCHANGE": 10,
    "UNKNOWN": 0,
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class AddressCluster:
    """Metadata for a named cluster of related addresses."""

    id: str
    name: str
    category: str
    description: str = ""
    confidence: int = 80  # 0-100 — how confident we are in this attribution
    addresses: List[str] = field(default_factory=list)

    @property
    def default_risk_score(self) -> int:
        return CATEGORY_RISK_DEFAULTS.get(self.category.upper(), 50)


@dataclass
class LookupResult:
    """Result of a cluster-based address lookup."""

    address: str
    cluster: AddressCluster
    risk_score: int
    category: str


# ---------------------------------------------------------------------------
# ClusterManager
# ---------------------------------------------------------------------------

class ClusterManager:
    """
    Manages address clusters, backed by an in-memory index plus the Sentinel
    database.

    The in-memory index is built from the static seed file and can be
    supplemented at runtime with dynamically discovered addresses.
    """

    def __init__(self, db: Database) -> None:
        self._db = db
        # cluster_id -> AddressCluster
        self._clusters: Dict[str, AddressCluster] = {}
        # address -> (cluster_id, risk_score, category)
        self._index: Dict[str, Tuple[str, int, str]] = {}

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load_from_file(self, path: str = config.KNOWN_ADDRESSES_FILE) -> int:
        """
        Load clusters and addresses from a JSON seed file.

        Expected JSON structure::

            {
              "clusters": [
                {
                  "id": "wannacry_2017",
                  "name": "WannaCry Ransomware 2017",
                  "category": "RANSOMWARE",
                  "description": "...",
                  "confidence": 99,
                  "addresses": [
                    {"address": "115p7...", "risk_score": 95, "notes": "..."},
                    ...
                  ]
                },
                ...
              ]
            }

        Returns the total number of addresses loaded.
        """
        if not os.path.isfile(path):
            logger.warning("Known-addresses file not found: %s", path)
            return 0

        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)

        total = 0
        for cluster_data in data.get("clusters", []):
            cluster = AddressCluster(
                id=cluster_data["id"],
                name=cluster_data["name"],
                category=cluster_data["category"].upper(),
                description=cluster_data.get("description", ""),
                confidence=cluster_data.get("confidence", 80),
            )
            # Persist cluster to DB
            self._db.add_cluster(
                cluster_id=cluster.id,
                name=cluster.name,
                category=cluster.category,
                description=cluster.description,
                confidence=cluster.confidence,
            )
            self._clusters[cluster.id] = cluster

            for addr_data in cluster_data.get("addresses", []):
                address = addr_data["address"]
                risk_score = addr_data.get(
                    "risk_score", cluster.default_risk_score
                )
                notes = addr_data.get("notes")

                cluster.addresses.append(address)
                self._index[address] = (cluster.id, risk_score, cluster.category)

                # Persist address to DB
                self._db.add_address(
                    address=address,
                    risk_score=risk_score,
                    category=cluster.category,
                    cluster_id=cluster.id,
                    notes=notes,
                )
                total += 1

        logger.info(
            "Loaded %d addresses across %d clusters from %s",
            total,
            len(data.get("clusters", [])),
            path,
        )
        return total

    # ------------------------------------------------------------------
    # Runtime management
    # ------------------------------------------------------------------

    def register_cluster(self, cluster: AddressCluster) -> None:
        """Register a cluster (and all its addresses) at runtime."""
        self._db.add_cluster(
            cluster_id=cluster.id,
            name=cluster.name,
            category=cluster.category,
            description=cluster.description,
            confidence=cluster.confidence,
        )
        self._clusters[cluster.id] = cluster
        for address in cluster.addresses:
            self._index[address] = (
                cluster.id,
                cluster.default_risk_score,
                cluster.category,
            )
            self._db.add_address(
                address=address,
                risk_score=cluster.default_risk_score,
                category=cluster.category,
                cluster_id=cluster.id,
            )

    def add_address_to_cluster(
        self,
        address: str,
        cluster_id: str,
        risk_score: Optional[int] = None,
        notes: Optional[str] = None,
    ) -> bool:
        """Dynamically add a single address to an existing cluster."""
        cluster = self._clusters.get(cluster_id)
        if cluster is None:
            logger.error("Cluster %s not found", cluster_id)
            return False

        score = risk_score if risk_score is not None else cluster.default_risk_score
        cluster.addresses.append(address)
        self._index[address] = (cluster_id, score, cluster.category)
        self._db.add_address(
            address=address,
            risk_score=score,
            category=cluster.category,
            cluster_id=cluster_id,
            notes=notes,
        )
        return True

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def lookup(self, address: str) -> Optional[LookupResult]:
        """
        Return a ``LookupResult`` if *address* belongs to any known cluster,
        otherwise ``None``.

        Checks the in-memory index first (O(1)), then falls back to the
        database (handles addresses added by other processes).
        """
        entry = self._index.get(address)
        if entry is not None:
            cluster_id, risk_score, category = entry
            cluster = self._clusters[cluster_id]
            return LookupResult(
                address=address,
                cluster=cluster,
                risk_score=risk_score,
                category=category,
            )

        # DB fallback
        db_record = self._db.get_address(address)
        if db_record:
            cluster_id = db_record.get("cluster_id", "")
            category = db_record.get("category", "UNKNOWN")
            risk_score = db_record.get("risk_score", 0)
            cluster = self._clusters.get(cluster_id) or AddressCluster(
                id=cluster_id or "db_only",
                name=db_record.get("notes") or category,
                category=category,
            )
            result = LookupResult(
                address=address,
                cluster=cluster,
                risk_score=risk_score,
                category=category,
            )
            # warm the in-memory cache
            if cluster_id:
                self._index[address] = (cluster_id, risk_score, category)
            return result

        return None

    def cluster_count(self) -> int:
        return len(self._clusters)

    def address_count(self) -> int:
        return len(self._index)

    def get_cluster(self, cluster_id: str) -> Optional[AddressCluster]:
        return self._clusters.get(cluster_id)

    def list_clusters(self) -> List[AddressCluster]:
        return list(self._clusters.values())
