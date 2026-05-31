"""
Step 2: For every wallet listed in wallets.json, download
  https://www.walletexplorer.com/wallet/<name>/addresses?format=csv&page=all
and save it under csvs/<Category>/<wallet>.csv

- Uses the user's webshare rotating proxy.
- Skips files that already exist (resume).
- Logs failures to download_failures.log.
- Concurrent (small pool) for throughput.
"""
import concurrent.futures as cf
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

PROXY = os.environ.get("WEBSHARE_PROXY_URL", "")
PROXIES = {"http": PROXY, "https": PROXY}
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

ROOT = Path(__file__).parent
OUT_DIR = ROOT / "csvs"
LOG_PATH = ROOT / "download_failures.log"
PROGRESS_PATH = ROOT / "download_progress.log"

MAX_WORKERS = 8
TIMEOUT = 90
RETRIES = 3
RETRY_SLEEP = 4  # seconds between retries


def safe_name(s: str) -> str:
    """Sanitize a wallet name into a filesystem-safe filename."""
    # Wallet names can contain dots and dashes; map disallowed chars to _
    s = s.strip()
    s = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "_", s)
    # Avoid trailing dots/spaces (Windows)
    s = s.rstrip(". ")
    return s or "_"


def safe_cat(s: str) -> str:
    s = s.strip().rstrip(":")
    s = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "_", s)
    s = s.replace("/", "_")
    return s or "uncategorized"


def url_for(wallet: str) -> str:
    return f"https://www.walletexplorer.com/wallet/{wallet}/addresses?format=csv&page=all"


def download_one(category: str, wallet: str) -> tuple[str, str, str]:
    """Returns (status, wallet, message). status in {ok, skip, fail}."""
    cat_dir = OUT_DIR / safe_cat(category)
    cat_dir.mkdir(parents=True, exist_ok=True)
    out_file = cat_dir / f"{safe_name(wallet)}.csv"

    if out_file.exists() and out_file.stat().st_size > 0:
        return ("skip", wallet, f"already exists ({out_file.stat().st_size} bytes)")

    url = url_for(wallet)
    last_err = None
    for attempt in range(1, RETRIES + 1):
        try:
            r = requests.get(
                url, headers=HEADERS, proxies=PROXIES,
                timeout=TIMEOUT, allow_redirects=True,
            )
            if r.status_code == 200 and r.text:
                # Some failures may return HTML even with 200 — check for CSV header
                # Wallets without addresses still typically return a header line.
                ctype = r.headers.get("Content-Type", "")
                body = r.text
                if "csv" not in ctype.lower() and not body.startswith(("\"#", "address,", "#")):
                    last_err = f"non-csv content-type={ctype}, body[:80]={body[:80]!r}"
                    time.sleep(RETRY_SLEEP)
                    continue
                out_file.write_text(body, encoding="utf-8", newline="")
                return ("ok", wallet, f"{len(body)} bytes -> {out_file}")
            else:
                last_err = f"http {r.status_code}, len={len(r.text)}"
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
        time.sleep(RETRY_SLEEP)
    return ("fail", wallet, last_err or "unknown error")


def main():
    data = json.loads((ROOT / "wallets.json").read_text(encoding="utf-8"))
    categories: dict[str, list[str]] = data["categories"]

    # Build a flat task list, but keep category for each
    tasks: list[tuple[str, str]] = []
    for cat, wallets in categories.items():
        for w in wallets:
            tasks.append((cat, w))

    total = len(tasks)
    print(f"Downloading {total} wallet CSVs into {OUT_DIR}", flush=True)
    OUT_DIR.mkdir(exist_ok=True)

    ok = skip = fail = 0
    with open(PROGRESS_PATH, "a", encoding="utf-8") as plog, \
         open(LOG_PATH, "a", encoding="utf-8") as flog, \
         cf.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = {ex.submit(download_one, c, w): (c, w) for c, w in tasks}
        done = 0
        for fut in cf.as_completed(futs):
            cat, wallet = futs[fut]
            try:
                status, name, msg = fut.result()
            except Exception as e:
                status, name, msg = ("fail", wallet, f"executor: {e}")
            done += 1
            line = f"[{done}/{total}] {status.upper():4} {cat} :: {name} :: {msg}"
            print(line, flush=True)
            plog.write(line + "\n")
            plog.flush()
            if status == "ok":
                ok += 1
            elif status == "skip":
                skip += 1
            else:
                fail += 1
                flog.write(line + "\n")
                flog.flush()

    print("\n=== SUMMARY ===", flush=True)
    print(f"ok:   {ok}", flush=True)
    print(f"skip: {skip}", flush=True)
    print(f"fail: {fail}", flush=True)
    print(f"failures logged to: {LOG_PATH}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        sys.exit(130)
