"""
Enumerate all on-chain blacklisted addresses for USDC and USDT on Ethereum.

Circle (USDC) and Tether (USDT) enforce blacklists at the ERC-20 contract
level. Blacklisted addresses cannot transfer or receive the token — the ban
is provable and permanent on-chain via emitted events.

This script fetches every Blacklisted / AddedBlackList event from Ethereum
mainnet using the Etherscan getLogs API, decodes the banned address from the
event topic, and writes a unified JSON file.

Requirements:
    pip install requests web3 python-dotenv

Environment variables:
    ETHERSCAN_API_KEY   – free key at https://etherscan.io/myapikey
    WEBSHARE_PROXY_URL  – optional rotating proxy (http://user:pass@host:port/)

Output:
    banned_addresses_unified.json
"""
from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import requests
from dotenv import load_dotenv
from web3 import Web3

# Load .env from this file's directory, then from project root (two levels up)
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

# ── configuration ─────────────────────────────────────────────────────────────

ETHERSCAN_API_KEY = os.environ.get("ETHERSCAN_API_KEY", "")
PROXY_URL = os.environ.get("WEBSHARE_PROXY_URL", "")
PROXIES = {"http": PROXY_URL, "https": PROXY_URL} if PROXY_URL else None

ETHERSCAN_URL = "https://api.etherscan.io/v2/api"  # V2 endpoint
ETHERSCAN_CHAIN_ID = 1  # Ethereum mainnet
OUTPUT_FILE = "banned_addresses_unified_etherscan.json"

MAX_WORKERS = 6
MAX_RETRIES = 5
CHUNK_SIZE = 100_000   # block range per request (~2 weeks of blocks)

# Approximate deployment block for each contract (start of scan)
DEPLOY_BLOCK = {
    "USDT": 4_634_748,   # Nov 2017
    "USDC": 6_082_465,   # Sep 2018
}

# ── contract definitions ──────────────────────────────────────────────────────
#
# topic0 is computed at runtime via keccak256 so there is no hardcoded hash
# to go stale. Verify manually:
#   Web3.keccak(text="AddedBlackList(address)").hex()
#   Web3.keccak(text="Blacklisted(address)").hex()

CONTRACTS = {
    "USDT": {
        "address": Web3.to_checksum_address("0xdac17f958d2ee523a2206206994597c13d831ec7"),
        "event":   "AddedBlackList(address)",
    },
    "USDC": {
        "address": Web3.to_checksum_address("0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"),
        "event":   "Blacklisted(address)",
    },
}

# Compute topic0 hashes once at startup
for cfg in CONTRACTS.values():
    cfg["topic0"] = Web3.keccak(text=cfg["event"]).hex()


# ── Etherscan API helpers ─────────────────────────────────────────────────────

def _call(params: dict) -> dict:
    params["chainid"] = ETHERSCAN_CHAIN_ID
    if ETHERSCAN_API_KEY:
        params["apikey"] = ETHERSCAN_API_KEY
    last_err: Optional[Exception] = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.get(ETHERSCAN_URL, params=params, proxies=PROXIES, timeout=30)
            r.raise_for_status()
            data = r.json()
            msg = data.get("message", "")
            result = data.get("result", "")
            if data.get("status") == "0" and msg == "NOTOK":
                raise RuntimeError(f"Etherscan: {result}")
            # Empty result is valid (no logs in range)
            if result == "Max rate limit reached":
                raise RuntimeError("Rate limit")
            return data
        except Exception as e:
            last_err = e
            wait = min(2 ** attempt, 30)
            print(f"  retry {attempt}/{MAX_RETRIES} after {wait}s: {e}", flush=True)
            time.sleep(wait)
    raise RuntimeError(f"Etherscan call failed: {last_err}")


def get_latest_block() -> int:
    data = _call({"module": "proxy", "action": "eth_blockNumber"})
    return int(data["result"], 16)


def get_logs(address: str, topic0: str, from_block: int, to_block: int) -> list[dict]:
    data = _call({
        "module":    "logs",
        "action":    "getLogs",
        "address":   address,
        "topic0":    topic0,
        "fromBlock": from_block,
        "toBlock":   to_block,
    })
    result = data.get("result", [])
    return result if isinstance(result, list) else []


# ── address decoder ───────────────────────────────────────────────────────────

def decode_address(log: dict) -> str:
    """
    The banned address is the first indexed topic (topics[1]).
    Indexed address topics are zero-padded to 32 bytes — take the last 20.
    Falls back to the data field for non-indexed events.
    """
    topics = log.get("topics", [])
    if len(topics) >= 2:
        raw = topics[1]  # "0x000...000<address>"
    else:
        raw = log.get("data", "0x")
    return Web3.to_checksum_address("0x" + raw[-40:]).lower()


# ── per-token fetcher ─────────────────────────────────────────────────────────

def fetch_bans(symbol: str, cfg: dict, latest_block: int) -> list[dict]:
    start = DEPLOY_BLOCK[symbol]
    end = latest_block
    chunks = [(s, min(s + CHUNK_SIZE - 1, end)) for s in range(start, end + 1, CHUNK_SIZE)]

    print(f"[{symbol}] blocks {start:,}→{end:,} | {len(chunks)} chunks", flush=True)

    all_logs: list[dict] = []
    done = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {
            ex.submit(get_logs, cfg["address"], cfg["topic0"], s, e): (s, e)
            for s, e in chunks
        }
        for fut in as_completed(futures):
            s, e = futures[fut]
            try:
                logs = fut.result()
                all_logs.extend(logs)
            except Exception as err:
                print(f"  [{symbol}] chunk {s:,}-{e:,} failed: {err}", flush=True)
            done += 1
            if done % 20 == 0 or done == len(chunks):
                print(f"  [{symbol}] {done}/{len(chunks)} chunks | {len(all_logs)} events", flush=True)

    records = []
    for log in all_logs:
        try:
            records.append({
                "address":   decode_address(log),
                "symbol":    symbol,
                "txhash":    log.get("transactionHash", ""),
                "block":     int(log.get("blockNumber", "0x0"), 16),
                "timestamp": int(log.get("timeStamp", "0x0"), 16),
                "contract":  cfg["address"].lower(),
            })
        except Exception as e:
            print(f"  [{symbol}] decode error: {e} | log={log}", flush=True)

    print(f"[{symbol}] {len(records)} ban events decoded\n", flush=True)
    return records


# ── entry point ───────────────────────────────────────────────────────────────

def main():
    if not ETHERSCAN_API_KEY:
        print(
            "WARNING: ETHERSCAN_API_KEY not set.\n"
            "Free-tier limit is 1 req/5s — scan will be very slow.\n"
            "Get a free key at https://etherscan.io/myapikey\n",
            file=sys.stderr,
            flush=True,
        )

    print("Fetching latest Ethereum block…", flush=True)
    latest = get_latest_block()
    print(f"Latest block: {latest:,}\n", flush=True)

    all_records: list[dict] = []
    for symbol, cfg in CONTRACTS.items():
        all_records.extend(fetch_bans(symbol, cfg, latest))

    # Deduplicate by (address, symbol) — keep the earliest ban block
    seen: dict[tuple, dict] = {}
    for rec in sorted(all_records, key=lambda r: r["block"]):
        key = (rec["address"], rec["symbol"])
        if key not in seen:
            seen[key] = rec
    deduped = list(seen.values())

    print(f"Total unique banned addresses: {len(deduped)}", flush=True)
    print(f"Writing {OUTPUT_FILE}…", flush=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(deduped, f, ensure_ascii=False, indent=2)
    print("Done.", flush=True)


if __name__ == "__main__":
    main()
