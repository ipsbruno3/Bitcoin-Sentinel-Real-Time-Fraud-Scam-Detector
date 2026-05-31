import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

PROXY = os.environ.get("WEBSHARE_PROXY_URL", "")
BASE_URL = "https://api.checkcryptoaddress.com/scam-reports"
OUTPUT_FILE = "scam_reports_all.json"
WORKERS = 16
MAX_RETRIES = 5

HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "cache-control": "no-cache",
    "origin": "https://checkcryptoaddress.com",
    "pragma": "no-cache",
    "priority": "u=1, i",
    "referer": "https://checkcryptoaddress.com/",
    "sec-ch-ua": '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-site",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
}

PROXIES = {"http": PROXY, "https": PROXY}


def fetch_page(page: int) -> dict:
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.get(
                BASE_URL,
                params={"page": page, "search": ""},
                headers=HEADERS,
                proxies=PROXIES,
                timeout=30,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            time.sleep(min(2 ** attempt, 15))
    raise RuntimeError(f"page {page} failed after {MAX_RETRIES} retries: {last_err}")


def main():
    print("Fetching page 1 to discover total pages...", flush=True)
    first = fetch_page(1)
    total_pages = first["page"]["total"]
    total_count = first["page"]["count"]
    print(f"Total pages: {total_pages} | Total records: {total_count}", flush=True)

    pages = {1: first}
    remaining = list(range(2, total_pages + 1))

    done = 1
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = {ex.submit(fetch_page, p): p for p in remaining}
        for fut in as_completed(futures):
            p = futures[fut]
            try:
                pages[p] = fut.result()
            except Exception as e:
                print(f"\n[!] Failed page {p}: {e}", file=sys.stderr, flush=True)
                pages[p] = {"data": [], "page": {"current": p, "error": str(e)}}
            done += 1
            if done % 25 == 0 or done == total_pages:
                print(f"  progress: {done}/{total_pages}", flush=True)

    merged_data = []
    for p in sorted(pages):
        merged_data.extend(pages[p].get("data", []))

    out = {
        "data": merged_data,
        "page": {
            "total": total_pages,
            "count": total_count,
            "fetched": len(merged_data),
        },
    }

    print(f"Writing {OUTPUT_FILE} ({len(merged_data)} records)...", flush=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("Done.", flush=True)


if __name__ == "__main__":
    main()
