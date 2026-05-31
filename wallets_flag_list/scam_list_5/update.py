"""
Refresh sanctioned crypto wallet lists.

Downloads:
  - OFAC sanctioned addresses (17 coins, txt+json) from 0xB10C/ofac-sanctioned-digital-currency-addresses
  - Israel MOD crypto sanctions (NDJSON) from OpenSanctions

Then extracts every CryptoWallet entity, infers missing currencies by address
format, and writes deduplicated per-coin TXT files plus a combined master list.

Run:
    python update.py
"""
from __future__ import annotations
import concurrent.futures as cf
import json
import os
import re
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime

ROOT         = os.path.dirname(os.path.abspath(__file__))
OFAC_DIR     = os.path.join(ROOT, "ofac")
OS_DIR       = os.path.join(ROOT, "opensanctions")
SNAPSHOTS_DIR = os.path.join(ROOT, "snapshots")

# Timestamped output dir for this run — preserves history across updates
RUN_TS       = datetime.now().strftime("%Y-%m-%d_%H%M%S")
COMBINED_DIR = os.path.join(SNAPSHOTS_DIR, RUN_TS)

for d in (OFAC_DIR, OS_DIR, SNAPSHOTS_DIR, COMBINED_DIR):
    os.makedirs(d, exist_ok=True)

OFAC_COINS = ["ARB","BCH","BSC","BSV","BTG","DASH","ETC","ETH","LTC","TRX",
              "USDC","USDT","XBT","XMR","XRP","XVG","ZEC"]
OFAC_BASE  = "https://raw.githubusercontent.com/0xB10C/ofac-sanctioned-digital-currency-addresses/lists"
IL_BASE    = "https://data.opensanctions.org/datasets/latest/il_mod_crypto"

CURRENCY_ALIASES = {
    "BTC":"XBT","BITCOIN":"XBT","XBT":"XBT",
    "ETH":"ETH","ETHER":"ETH","ETHEREUM":"ETH",
    "USDT":"USDT","USDC":"USDC",
    "TRX":"TRX","TRON":"TRX",
    "LTC":"LTC","LITECOIN":"LTC",
    "XMR":"XMR","MONERO":"XMR",
    "DASH":"DASH","ZEC":"ZEC","ZCASH":"ZEC",
    "BCH":"BCH","BSV":"BSV","BTG":"BTG","ETC":"ETC",
    "ARB":"ARB","BSC":"BSC","BNB":"BSC",
    "XRP":"XRP","XVG":"XVG",
}

_RX_ETH        = re.compile(r"^0x[a-fA-F0-9]{40}$")
_RX_BTC_LEGACY = re.compile(r"^[13][a-km-zA-HJ-NP-Z1-9]{25,34}$")
_RX_BTC_BECH32 = re.compile(r"^(bc1|tb1)[02-9ac-hj-np-z]{6,87}$")
_RX_LTC        = re.compile(r"^(ltc1[02-9ac-hj-np-z]{6,87}|[LM3][a-km-zA-HJ-NP-Z1-9]{26,33})$")
_RX_TRX        = re.compile(r"^T[a-km-zA-HJ-NP-Z1-9]{33}$")
_RX_XMR        = re.compile(r"^[48][0-9AB][a-zA-Z0-9]{93,104}$")
_RX_DASH       = re.compile(r"^X[a-km-zA-HJ-NP-Z1-9]{33}$")
_RX_ZEC_T      = re.compile(r"^t[13][a-km-zA-HJ-NP-Z1-9]{33}$")
_RX_BCH_CASH   = re.compile(r"^(bitcoincash:|bchtest:)?[qp][a-z0-9]{40,}$", re.IGNORECASE)
_RX_XRP        = re.compile(r"^r[1-9A-HJ-NP-Za-km-z]{24,34}$")

def infer_currency(addr: str) -> str:
    if _RX_ETH.match(addr):        return "ETH"
    if _RX_BTC_BECH32.match(addr): return "XBT"
    if _RX_BTC_LEGACY.match(addr): return "XBT"
    if _RX_LTC.match(addr):        return "LTC"
    if _RX_TRX.match(addr):        return "TRX"
    if _RX_XMR.match(addr):        return "XMR"
    if _RX_DASH.match(addr):       return "DASH"
    if _RX_ZEC_T.match(addr):      return "ZEC"
    if _RX_BCH_CASH.match(addr):   return "BCH"
    if _RX_XRP.match(addr):        return "XRP"
    return ""


def download(url: str, dest: str) -> tuple[str, int]:
    req = urllib.request.Request(url, headers={"User-Agent": "scam-list-updater/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as out:
        data = r.read()
        out.write(data)
    return dest, len(data)


def fetch_all() -> None:
    jobs: list[tuple[str, str]] = []
    for coin in OFAC_COINS:
        jobs.append((f"{OFAC_BASE}/sanctioned_addresses_{coin}.txt",
                     os.path.join(OFAC_DIR, f"sanctioned_addresses_{coin}.txt")))
        jobs.append((f"{OFAC_BASE}/sanctioned_addresses_{coin}.json",
                     os.path.join(OFAC_DIR, f"sanctioned_addresses_{coin}.json")))
    jobs.append((f"{OFAC_BASE}/README.md", os.path.join(OFAC_DIR, "README.md")))
    jobs.append((f"{IL_BASE}/targets.simple.csv",
                 os.path.join(OS_DIR, "il_mod_crypto.simple.csv")))
    jobs.append((f"{IL_BASE}/targets.nested.json",
                 os.path.join(OS_DIR, "il_mod_crypto.nested.json")))

    print(f"Downloading {len(jobs)} files...")
    with cf.ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(download, url, dest): (url, dest) for url, dest in jobs}
        ok, failed = 0, 0
        for fut in cf.as_completed(futures):
            url, dest = futures[fut]
            try:
                _, n = fut.result()
                ok += 1
                print(f"  ok  {os.path.basename(dest):<40} {n:>10,} bytes")
            except Exception as e:
                failed += 1
                print(f"  ERR {os.path.basename(dest):<40} {e}")
        print(f"Downloaded {ok}/{ok + failed} files.")


# {coin: {address: set(sources)}}
addrs: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
master: dict[str, list] = {}  # addr -> [coin, set(sources)]


def add_address(addr: str, coin: str, source: str) -> None:
    if not addr:
        return
    addr = addr.strip()
    if not addr:
        return
    coin = coin.upper()
    bucket = CURRENCY_ALIASES.get(coin, coin if coin else "")
    if not bucket or bucket == "UNKNOWN":
        bucket = infer_currency(addr) or "UNKNOWN"
    addrs[bucket][addr].add(source)
    if addr not in master:
        master[addr] = [bucket, {source}]
    else:
        existing_coin, srcs = master[addr]
        srcs.add(source)
        if existing_coin == "UNKNOWN" and bucket != "UNKNOWN":
            master[addr][0] = bucket


def walk_for_wallets(node, source: str) -> None:
    if isinstance(node, dict):
        if node.get("schema") == "CryptoWallet":
            props = node.get("properties", {}) or {}
            pubkeys = props.get("publicKey") or []
            currencies = props.get("currency") or []
            currency = (currencies[0] if currencies else "").upper() if currencies else ""
            for pk in pubkeys:
                add_address(pk, currency or "UNKNOWN", source)
        for v in node.values():
            if isinstance(v, (dict, list)):
                walk_for_wallets(v, source)
    elif isinstance(node, list):
        for item in node:
            walk_for_wallets(item, source)


def merge() -> None:
    addrs.clear()
    master.clear()

    for coin in OFAC_COINS:
        p = os.path.join(OFAC_DIR, f"sanctioned_addresses_{coin}.txt")
        if not os.path.exists(p):
            continue
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                a = line.strip()
                if a:
                    add_address(a, coin, "ofac_0xB10C")

    il_path = os.path.join(OS_DIR, "il_mod_crypto.nested.json")
    if os.path.exists(il_path):
        with open(il_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                walk_for_wallets(obj, "il_mod_crypto")

    for coin, mapping in sorted(addrs.items()):
        out = os.path.join(COMBINED_DIR, f"{coin}.txt")
        with open(out, "w", encoding="utf-8", newline="\n") as f:
            for a in sorted(mapping.keys()):
                f.write(a + "\n")

    with open(os.path.join(COMBINED_DIR, "all_addresses.txt"), "w", encoding="utf-8", newline="\n") as f:
        for a in sorted(master.keys()):
            f.write(a + "\n")

    with open(os.path.join(COMBINED_DIR, "all_addresses_with_currency.tsv"), "w", encoding="utf-8", newline="\n") as f:
        f.write("address\tcurrency\tsources\n")
        for a in sorted(master.keys()):
            coin, srcs = master[a]
            f.write(f"{a}\t{coin}\t{','.join(sorted(srcs))}\n")

    src_counts: dict[str, int] = defaultdict(int)
    for _, srcs in master.values():
        for s in srcs:
            src_counts[s] += 1

    lines = [f"Total unique addresses: {len(master)}", "", "Per-coin counts:"]
    for coin in sorted(addrs.keys()):
        lines.append(f"  {coin:<8} {len(addrs[coin])}")
    lines += ["", "Per-source counts (an address can appear in multiple sources):"]
    for s in sorted(src_counts.keys()):
        lines.append(f"  {s:<22} {src_counts[s]}")
    summary = "\n".join(lines) + "\n"
    with open(os.path.join(COMBINED_DIR, "summary.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write(summary)
    print("\n" + summary)


def main() -> int:
    skip_download = "--no-fetch" in sys.argv
    if not skip_download:
        fetch_all()
    merge()

    # Mirror the snapshot to snapshots/latest/ for easy access
    import shutil
    latest = os.path.join(SNAPSHOTS_DIR, "latest")
    if os.path.isdir(latest):
        shutil.rmtree(latest)
    shutil.copytree(COMBINED_DIR, latest)

    print(f"\nSnapshot saved to: snapshots/{RUN_TS}/")
    print(f"Latest updated:    snapshots/latest/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
