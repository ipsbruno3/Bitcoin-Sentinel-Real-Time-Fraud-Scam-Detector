"""
Bitcoin Sentinel — CLI entry point.

Usage
-----
    python main.py [OPTIONS]

Options
-------
    --db PATH           Path to the SQLite database file
                        (default: data/sentinel.db)
    --seed FILE         Path to known-addresses JSON seed file
                        (default: data/known_addresses.json)
    --threshold N       Minimum risk score (0-100) required to emit an alert
                        (default: 61)
    --json              Emit machine-readable JSON lines instead of
                        human-readable output
    --list-clusters     Print all loaded clusters and exit
    --list-alerts N     Print the last N alerts and exit (default: 20)
    --ws-url URL        Override the WebSocket feed URL
    --no-exchange-filter
                        Disable WalletExplorer exchange filtering
    --log-level LEVEL   Logging verbosity: DEBUG / INFO / WARNING / ERROR
                        (default: INFO)

Examples
--------
    # Start monitoring with defaults
    python main.py

    # Emit JSON output and lower the alert threshold
    python main.py --json --threshold 50

    # Show loaded clusters without starting the monitor
    python main.py --list-clusters
"""

import argparse
import asyncio
import logging
import sys
from typing import Optional

from sentinel import config
from sentinel.alerts import AlertManager
from sentinel.classifier import TransactionClassifier
from sentinel.clusters import ClusterManager
from sentinel.database import Database
from sentinel.exchange_filter import ExchangeFilter
from sentinel.monitor import Monitor


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=config.LOG_FORMAT,
        stream=sys.stderr,
    )


# ---------------------------------------------------------------------------
# CLI parsing
# ---------------------------------------------------------------------------

def _parse_args(argv: Optional[list] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="bitcoin-sentinel",
        description="Real-time Bitcoin fraud and scam detection engine.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--db",
        default=config.DB_PATH,
        metavar="PATH",
        help="SQLite database path (default: %(default)s)",
    )
    parser.add_argument(
        "--seed",
        default=config.KNOWN_ADDRESSES_FILE,
        metavar="FILE",
        help="Known-addresses JSON seed file (default: %(default)s)",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=config.ALERT_THRESHOLD,
        metavar="N",
        help="Minimum risk score (0-100) to emit an alert (default: %(default)s)",
    )
    parser.add_argument(
        "--json",
        dest="output_json",
        action="store_true",
        help="Emit JSON lines instead of human-readable output",
    )
    parser.add_argument(
        "--list-clusters",
        action="store_true",
        help="Print all loaded clusters and exit",
    )
    parser.add_argument(
        "--list-alerts",
        type=int,
        nargs="?",
        const=20,
        metavar="N",
        help="Print the last N alerts and exit (default: 20)",
    )
    parser.add_argument(
        "--ws-url",
        default=config.BTC_WS_URL,
        metavar="URL",
        help="WebSocket feed URL (default: %(default)s)",
    )
    parser.add_argument(
        "--no-exchange-filter",
        dest="exchange_filter",
        action="store_false",
        default=True,
        help="Disable WalletExplorer exchange-wallet filtering",
    )
    parser.add_argument(
        "--log-level",
        default=config.LOG_LEVEL,
        metavar="LEVEL",
        help="Logging level: DEBUG/INFO/WARNING/ERROR (default: %(default)s)",
    )
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

def _bootstrap(args: argparse.Namespace):
    """Initialise and return all Sentinel components."""
    db = Database(db_path=args.db)

    cluster_mgr = ClusterManager(db)
    loaded = cluster_mgr.load_from_file(path=args.seed)
    logging.getLogger(__name__).info(
        "Loaded %d addresses across %d clusters.",
        loaded,
        cluster_mgr.cluster_count(),
    )

    exchange_filter = ExchangeFilter() if args.exchange_filter else _NullExchangeFilter()

    classifier = TransactionClassifier(
        cluster_manager=cluster_mgr,
        exchange_filter=exchange_filter,
    )

    alert_mgr = AlertManager(
        db=db,
        threshold=args.threshold,
        output_json=args.output_json,
    )

    return db, cluster_mgr, classifier, alert_mgr


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def _cmd_list_clusters(cluster_mgr: ClusterManager) -> None:
    clusters = cluster_mgr.list_clusters()
    if not clusters:
        print("No clusters loaded.")
        return
    print(f"{'ID':<30} {'Category':<12} {'Confidence':>10}  Name")
    print("─" * 72)
    for c in clusters:
        print(
            f"{c.id:<30} {c.category:<12} {c.confidence:>10}  {c.name}"
        )
    print(f"\n{len(clusters)} cluster(s) / {cluster_mgr.address_count()} address(es) loaded.")


def _cmd_list_alerts(db: Database, n: int) -> None:
    alerts = db.list_alerts(limit=n)
    if not alerts:
        print("No alerts recorded yet.")
        return
    print(f"{'#':<6} {'Timestamp':<26} {'Score':>5}  {'Category':<12}  {'TX Hash':<64}  Address")
    print("─" * 130)
    for a in alerts:
        print(
            f"{a['id']:<6} {a['timestamp']:<26} {a['risk_score']:>5}"
            f"  {a['category']:<12}  {a['tx_hash']:<64}  {a['address']}"
        )
    print(f"\n{len(alerts)} alert(s) shown.")


async def _cmd_monitor(
    classifier: TransactionClassifier,
    alert_mgr: AlertManager,
    ws_url: str,
    exchange_filter: "ExchangeFilter",
) -> None:
    monitor = Monitor(
        classifier=classifier,
        alert_manager=alert_mgr,
        ws_url=ws_url,
    )
    try:
        await monitor.run()
    finally:
        await exchange_filter.close()


# ---------------------------------------------------------------------------
# Null exchange filter (used when --no-exchange-filter is set)
# ---------------------------------------------------------------------------

class _NullExchangeFilter(ExchangeFilter):
    """No-op exchange filter that always returns False / None."""

    async def get_wallet_label(self, address: str):
        return None

    async def is_exchange(self, address: str) -> bool:
        return False

    async def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def cli_main() -> None:
    args = _parse_args()
    _setup_logging(args.log_level)

    db, cluster_mgr, classifier, alert_mgr = _bootstrap(args)

    if args.list_clusters:
        _cmd_list_clusters(cluster_mgr)
        return

    if args.list_alerts is not None:
        _cmd_list_alerts(db, args.list_alerts)
        return

    # Resolve the exchange_filter for cleanup on exit
    exchange_filter = (
        ExchangeFilter() if args.exchange_filter else _NullExchangeFilter()
    )
    # Re-wire classifier to share the same filter instance
    classifier.set_exchange_filter(exchange_filter)

    print(
        "🛡️  Bitcoin Sentinel — monitoring live Bitcoin transactions …\n"
        f"   Feed    : {args.ws_url}\n"
        f"   Database: {args.db}\n"
        f"   Clusters: {cluster_mgr.cluster_count()} "
        f"({cluster_mgr.address_count()} addresses)\n"
        f"   Threshold: {args.threshold}/100\n"
        "Press Ctrl+C to stop.\n"
        + "─" * 72,
        file=sys.stderr,
    )

    try:
        asyncio.run(
            _cmd_monitor(classifier, alert_mgr, args.ws_url, exchange_filter)
        )
    except KeyboardInterrupt:
        print("\nStopped by user.", file=sys.stderr)


if __name__ == "__main__":
    cli_main()
