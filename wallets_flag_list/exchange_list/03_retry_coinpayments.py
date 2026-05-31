"""
Special-case fetch for CoinPayments.net which has ~95,768 pages of
addresses. The single page=all response is too large for the rotating
proxy to deliver reliably (chunked-encoding drops). Strategy:
  1) Try page=all once with stream=True, writing chunks straight to
     disk so we never hold the whole body in memory.
  2) If that fails, fall back to fetching pages 1..N via concurrent
     requests and concatenating into one CSV.
"""
from __future__ import annotations

import concurrent.futures as cf
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
    ),
    "Accept-Encoding": "identity",
}

ROOT = Path(__file__).parent
OUT = ROOT / "csvs" / "Services_others" / "CoinPayments.net.csv"
WALLET = "CoinPayments.net"


def try_stream_all() -> bool:
    url = f"https://www.walletexplorer.com/wallet/{WALLET}/addresses?format=csv&page=all"
    print(f"[stream] GET {url}", flush=True)
    try:
        with requests.get(url, headers=HEADERS, proxies=PROXIES, stream=True, timeout=(60, 600)) as r:
            r.raise_for_status()
            tmp = OUT.with_suffix(".csv.part")
            written = 0
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    f.write(chunk)
                    written += len(chunk)
                    if written % (5 * 1024 * 1024) < 64 * 1024:
                        print(f"[stream] {written/1024/1024:.1f} MB so far", flush=True)
            tmp.rename(OUT)
            print(f"[stream] OK total {written} bytes -> {OUT}", flush=True)
            return True
    except Exception as e:
        print(f"[stream] failed: {type(e).__name__}: {e}", flush=True)
        return False


def get_total_pages() -> int:
    url = f"https://www.walletexplorer.com/wallet/{WALLET}/addresses?format=csv&page=1"
    r = requests.get(url, headers=HEADERS, proxies=PROXIES, timeout=60)
    r.raise_for_status()
    m = re.search(r"Page \d+ from (\d+)", r.text)
    if not m:
        raise RuntimeError(f"Could not detect page count from: {r.text[:200]!r}")
    return int(m.group(1))


def fetch_page(p: int, retries: int = 5) -> tuple[int, str]:
    url = f"https://www.walletexplorer.com/wallet/{WALLET}/addresses?format=csv&page={p}"
    last = None
    for _ in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, proxies=PROXIES, timeout=60)
            if r.status_code == 200 and r.text.startswith(("\"#", "address,", "#")):
                return p, r.text
            last = f"http {r.status_code}, head={r.text[:60]!r}"
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
        time.sleep(2)
    raise RuntimeError(f"page {p} failed: {last}")


def paginated_assemble():
    total = get_total_pages()
    print(f"[paginated] total pages: {total}", flush=True)
    pages_dir = ROOT / "coinpayments_pages"
    pages_dir.mkdir(exist_ok=True)

    # Resume: skip pages already saved
    todo = []
    for p in range(1, total + 1):
        f = pages_dir / f"{p}.csv"
        if f.exists() and f.stat().st_size > 0:
            continue
        todo.append(p)
    print(f"[paginated] {len(todo)} pages to fetch (already have {total-len(todo)})", flush=True)

    failed: list[int] = []
    done = 0
    with cf.ThreadPoolExecutor(max_workers=64) as ex:
        futs = {ex.submit(fetch_page, p): p for p in todo}
        for fut in cf.as_completed(futs):
            p = futs[fut]
            try:
                pn, body = fut.result()
                (pages_dir / f"{pn}.csv").write_text(body, encoding="utf-8", newline="")
                done += 1
                if done % 200 == 0 or done == len(todo):
                    print(f"[paginated] {done}/{len(todo)} pages saved", flush=True)
            except Exception as e:
                print(f"[paginated] page {p} FAILED: {e}", flush=True)
                failed.append(p)

    if failed:
        # one more sequential pass
        print(f"[paginated] retrying {len(failed)} pages sequentially", flush=True)
        still = []
        for p in failed:
            try:
                pn, body = fetch_page(p, retries=8)
                (pages_dir / f"{pn}.csv").write_text(body, encoding="utf-8", newline="")
            except Exception as e:
                print(f"[paginated] page {p} STILL FAILED: {e}", flush=True)
                still.append(p)
        if still:
            print(f"[paginated] giving up on {len(still)} pages: {still[:20]}...", flush=True)
            return False

    # Concatenate all pages into one CSV. Keep header from page 1, drop
    # the per-page header lines from pages 2..N.
    print("[paginated] concatenating pages into final csv...", flush=True)
    with open(OUT, "w", encoding="utf-8", newline="") as out:
        first = True
        for p in range(1, total + 1):
            text = (pages_dir / f"{p}.csv").read_text(encoding="utf-8")
            lines = text.splitlines()
            if not lines:
                continue
            if first:
                # Keep the "#Wallet ..." comment plus the column header plus rows
                out.write(text if text.endswith("\n") else text + "\n")
                first = False
            else:
                # Skip the leading "#Wallet ..." comment line and the
                # "address,balance,..." column header. Keep only rows.
                rows = []
                for ln in lines:
                    if ln.startswith("\"#") or ln.startswith("#"):
                        continue
                    if ln.startswith("address,"):
                        continue
                    rows.append(ln)
                if rows:
                    out.write("\n".join(rows) + "\n")
    sz = OUT.stat().st_size
    print(f"[paginated] wrote {sz} bytes -> {OUT}", flush=True)
    return True


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    if try_stream_all():
        return
    print("\n[fallback] streaming failed -- using paginated assembly", flush=True)
    if not paginated_assemble():
        sys.exit(1)


if __name__ == "__main__":
    main()
