"""
Unify all flagged wallet address lists into a single normalized file.

Output schema (one JSON object per line — NDJSON):
    {"source": "...", "addr": "...", "network": "..."}

Network is the canonical chain ticker (BTC, ETH, XRP, LTC, TRX, etc.)
or "ALL" when the source does not specify a chain.

Sources included:
    scam_list_1   – CheckCryptoAddress.com scam reports
    scam_list_4   – EVM flagged addresses (plain 0x list)
    scam_list_5   – OFAC + OpenSanctions (multi-coin, via snapshots/latest)
    eth_blacklist – On-chain USDC/USDT banned addresses (Etherscan)

Sources excluded:
    exchange_list – allowlist (38M+ exchange addresses used to filter
                    false positives, not flagged wallets)

Run:
    python unify.py [--output PATH]       default: unified_flagged.ndjson
    python unify.py --output out.ndjson
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Iterator

ROOT = os.path.dirname(os.path.abspath(__file__))

# ── network normalisation ─────────────────────────────────────────────────────

_NETWORK_MAP = {
    "XBT": "BTC", "BITCOIN": "BTC", "BTC": "BTC",
    "ETH": "ETH", "ETHER": "ETH", "ETHEREUM": "ETH",
    "ETC": "ETC",
    "USDT": "ETH", "USDC": "ETH",    # ERC-20 stablecoins live on ETH
    "TRX": "TRX", "TRON": "TRX",
    "LTC": "LTC", "LITECOIN": "LTC",
    "XMR": "XMR", "MONERO": "XMR",
    "XRP": "XRP",
    "DASH": "DASH",
    "ZEC": "ZEC",
    "BCH": "BCH",
    "BSV": "BSV",
    "BTG": "BTG",
    "ARB": "ARB",
    "BSC": "BSC", "BNB": "BSC",
    "XLM": "XLM",
    "XVG": "XVG",
    "SOL": "SOL",
    "DOGE": "DOGE",
    "DGB": "DGB",
    "ADA": "ADA",
    "ALGO": "ALGO",
    "IOST": "IOST",
    "KMD": "KMD",
    "LSK": "LSK",
    "SC": "SC",
    "STRAT": "STRAT",
    "UNKNOWN": "ALL",
}

def norm_network(raw: str) -> str:
    return _NETWORK_MAP.get(raw.upper().strip(), raw.upper().strip() or "ALL")


# ── per-source readers ────────────────────────────────────────────────────────

def read_scam_list_1() -> Iterator[dict]:
    """
    CheckCryptoAddress.com scam reports.
    Tries scam_reports_all.json first, then the snapshot file.
    Each record may have: address/wallet, coin/currency/network.
    """
    candidates = [
        os.path.join(ROOT, "scam_list_1", "scam_reports_all.json"),
        os.path.join(ROOT, "scam_list_1", "scam_reports_all_snapshot.json"),
    ]
    for path in candidates:
        if not os.path.isfile(path) or os.path.getsize(path) == 0:
            continue
        try:
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
            items = raw.get("data", raw) if isinstance(raw, dict) else raw
            if not isinstance(items, list):
                continue
            for rec in items:
                if not isinstance(rec, dict):
                    continue
                addr = (
                    rec.get("address") or rec.get("wallet") or
                    rec.get("addr") or rec.get("cryptoAddress") or ""
                ).strip()
                if not addr:
                    continue
                network = norm_network(
                    rec.get("coin") or rec.get("currency") or
                    rec.get("network") or rec.get("type") or ""
                )
                yield {"source": "checkcryptoaddress", "addr": addr, "network": network}
            return  # used the first valid file
        except Exception as e:
            print(f"  [scam_list_1] skipping {os.path.basename(path)}: {e}", file=sys.stderr)


def read_scam_list_4() -> Iterator[dict]:
    """
    Plain list of EVM flagged addresses (0x…).
    No network field — inferred as ETH from address format.
    """
    path = os.path.join(ROOT, "scam_list_4", "address.json")
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return
    try:
        with open(path, encoding="utf-8") as f:
            items = json.load(f)
        if not isinstance(items, list):
            return
        for entry in items:
            addr = (entry.strip() if isinstance(entry, str)
                    else (entry.get("address") or entry.get("addr") or "").strip()
                    if isinstance(entry, dict) else "")
            if addr:
                yield {"source": "scam_list_4", "addr": addr.lower(), "network": "ETH"}
    except Exception as e:
        print(f"  [scam_list_4] error: {e}", file=sys.stderr)


def read_scam_list_5() -> Iterator[dict]:
    """
    OFAC + OpenSanctions sanctioned addresses.
    Reads from snapshots/latest/all_addresses_with_currency.tsv if available,
    falls back to combined/all_addresses_with_currency.tsv.
    TSV columns: address  currency  sources
    """
    candidates = [
        os.path.join(ROOT, "scam_list_5", "snapshots", "latest", "all_addresses_with_currency.tsv"),
        os.path.join(ROOT, "scam_list_5", "combined", "all_addresses_with_currency.tsv"),
    ]
    for path in candidates:
        if not os.path.isfile(path) or os.path.getsize(path) == 0:
            continue
        try:
            with open(path, encoding="utf-8") as f:
                header = f.readline()  # skip header line
                for line in f:
                    parts = line.rstrip("\n").split("\t")
                    if len(parts) < 2:
                        continue
                    addr, currency = parts[0].strip(), parts[1].strip()
                    if not addr:
                        continue
                    sources = parts[2].strip() if len(parts) > 2 else ""
                    # Build a descriptive source string
                    src_label = "ofac_opensanctions"
                    if sources:
                        src_label = sources.replace(",", "+")
                    yield {
                        "source": src_label,
                        "addr": addr,
                        "network": norm_network(currency),
                    }
            return  # used the first valid file
        except Exception as e:
            print(f"  [scam_list_5] skipping {os.path.basename(path)}: {e}", file=sys.stderr)


def read_eth_blacklist() -> Iterator[dict]:
    """
    On-chain USDC/USDT banned addresses from Etherscan.
    Schema: {address, symbol, txhash, block, timestamp, contract}
    """
    candidates = [
        os.path.join(ROOT, "eth_blacklist", "banned_addresses_unified_etherscan.json"),
        os.path.join(ROOT, "eth_blacklist", "banned_addresses_unified.json"),
    ]
    for path in candidates:
        if not os.path.isfile(path) or os.path.getsize(path) == 0:
            continue
        try:
            with open(path, encoding="utf-8") as f:
                items = json.load(f)
            if not isinstance(items, list):
                continue
            for rec in items:
                addr = rec.get("address", "").strip()
                if not addr:
                    continue
                symbol = rec.get("symbol", "")
                source = f"eth_blacklist_{symbol.lower()}" if symbol else "eth_blacklist"
                yield {"source": source, "addr": addr, "network": "ETH"}
            return
        except Exception as e:
            print(f"  [eth_blacklist] skipping {os.path.basename(path)}: {e}", file=sys.stderr)


# ── all sources ───────────────────────────────────────────────────────────────

READERS = [
    ("scam_list_1",   read_scam_list_1),
    ("scam_list_4",   read_scam_list_4),
    ("scam_list_5",   read_scam_list_5),
    ("eth_blacklist", read_eth_blacklist),
]


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Unify all flagged wallet lists")
    parser.add_argument("--output", default=os.path.join(ROOT, "unified_flagged.ndjson"),
                        help="Output path (default: wallets_flag_list/unified_flagged.ndjson)")
    args = parser.parse_args()

    seen: set[tuple] = set()
    counts: dict[str, int] = {}
    total = dupes = 0

    print(f"Writing to: {args.output}\n")

    with open(args.output, "w", encoding="utf-8") as out:
        for label, reader in READERS:
            n = 0
            try:
                for rec in reader():
                    key = (rec["addr"].lower(), rec["network"])
                    if key in seen:
                        dupes += 1
                        continue
                    seen.add(key)
                    out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    n += 1
                    total += 1
            except Exception as e:
                print(f"  [{label}] fatal error: {e}", file=sys.stderr)
            counts[label] = n
            print(f"  {label:<20} {n:>8,} records")

    print(f"\n{'='*38}")
    print(f"  Total unique  : {total:>8,}")
    print(f"  Duplicates    : {dupes:>8,}")
    print(f"  Output        : {args.output}")


if __name__ == "__main__":
    main()
