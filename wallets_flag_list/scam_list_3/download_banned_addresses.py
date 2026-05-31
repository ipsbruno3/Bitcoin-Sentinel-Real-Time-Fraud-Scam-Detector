"""
Download all on-chain banned addresses for USDC and USDT on the EVM.

Circle (USDC) and Tether (USDT) enforce blacklists at the smart contract
level: blacklisted addresses cannot transfer or receive the token.
This script fetches those ban records from the tokenview.io API and
merges them into a single JSON file.

Output: banned_addresses_unified.json
"""
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

# ── configuration ────────────────────────────────────────────────────────────

PROXY_URL = os.environ.get("WEBSHARE_PROXY_URL", "")
PROXIES = {"http": PROXY_URL, "https": PROXY_URL} if PROXY_URL else None

OUTPUT_FILE = "banned_addresses_unified.json"
PAGE_SIZE = 50
MAX_WORKERS = 8
MAX_RETRIES = 5

HEADERS = {
    "accept": "application/json, text/plain, */*",
    "origin": "https://tokenview.io",
    "referer": "https://tokenview.io/",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}

# Token contract addresses (Ethereum mainnet)
TOKENS = {
    "USDT": "0xdac17f958d2ee523a2206206994597c13d831ec7",
    "USDC": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
}

BASE_URL = "https://usdt.tokenview.io/v2api/chart/getBanned"


# ── helpers ───────────────────────────────────────────────────────────────────

def fetch_page(symbol: str, token_address: str, page: int) -> dict:
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.get(
                BASE_URL,
                params={"tokenAddr": token_address, "page": page, "size": PAGE_SIZE},
                headers=HEADERS,
                proxies=PROXIES,
                timeout=30,
            )
            r.raise_for_status()
            data = r.json()
            return data
        except Exception as e:
            last_err = e
            time.sleep(min(2 ** attempt, 15))
    raise RuntimeError(
        f"[{symbol}] page {page} failed after {MAX_RETRIES} retries: {last_err}"
    )


def fetch_all(symbol: str, token_address: str) -> list[dict]:
    print(f"[{symbol}] fetching page 1 to discover total count…", flush=True)
    first = fetch_page(symbol, token_address, 1)

    # tokenview wraps results in data.list / data.total — adjust if API changes
    total_count = first.get("data", {}).get("total", 0)
    records = first.get("data", {}).get("list", [])

    if total_count == 0:
        print(f"[{symbol}] no records found.", flush=True)
        return records

    total_pages = (total_count + PAGE_SIZE - 1) // PAGE_SIZE
    print(f"[{symbol}] {total_count} records across {total_pages} pages", flush=True)

    remaining = list(range(2, total_pages + 1))
    done = 1

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(fetch_page, symbol, token_address, p): p for p in remaining}
        for fut in as_completed(futures):
            p = futures[fut]
            try:
                page_data = fut.result()
                records.extend(page_data.get("data", {}).get("list", []))
            except Exception as e:
                print(f"  [{symbol}] page {p} failed: {e}", flush=True)
            done += 1
            if done % 10 == 0 or done == total_pages:
                print(f"  [{symbol}] progress: {done}/{total_pages}", flush=True)

    # tag each record with its symbol so the merged file is self-describing
    for rec in records:
        rec.setdefault("symbol", symbol)

    return records


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    all_records = []

    for symbol, token_address in TOKENS.items():
        records = fetch_all(symbol, token_address)
        all_records.extend(records)
        print(f"[{symbol}] {len(records)} records collected", flush=True)

    # deduplicate by (address, symbol)
    seen = set()
    deduped = []
    for rec in all_records:
        key = (rec.get("address", "").lower(), rec.get("symbol", ""))
        if key not in seen:
            seen.add(key)
            deduped.append(rec)

    print(f"\nTotal unique banned addresses: {len(deduped)}", flush=True)
    print(f"Writing {OUTPUT_FILE}…", flush=True)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(deduped, f, ensure_ascii=False, indent=2)

    print("Done.", flush=True)


if __name__ == "__main__":
    main()
