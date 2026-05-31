"""
Step 1: Scrape walletexplorer.com homepage to extract all wallet links
grouped by category (Exchanges, Pools, Services, Gambling, Old/historic, etc.).

Saves: wallets.json with {category: [wallet_name, ...]}
"""
import json
import os
import re
import sys
import requests
from bs4 import BeautifulSoup

PROXY = os.environ.get("WEBSHARE_PROXY_URL", "")
PROXIES = {"http": PROXY, "https": PROXY}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

URL = "https://www.walletexplorer.com/"


def main():
    print(f"Fetching {URL} via proxy...", flush=True)
    r = requests.get(URL, headers=HEADERS, proxies=PROXIES, timeout=60)
    r.raise_for_status()
    print(f"Got {len(r.text)} bytes (status {r.status_code})", flush=True)

    soup = BeautifulSoup(r.text, "lxml")

    # Save raw HTML for reference
    with open("homepage.html", "w", encoding="utf-8") as f:
        f.write(r.text)

    # The homepage groups wallets in tables under category headers.
    # Strategy: walk through the document; track current heading; when we
    # find a link to /wallet/<name>, attach it to the current heading.
    categories = {}
    current_cat = "uncategorized"

    # Find the central content area (rough)
    for el in soup.descendants:
        name = getattr(el, "name", None)
        if name in ("h1", "h2", "h3", "h4", "th"):
            text = el.get_text(strip=True)
            if text:
                # th headers like "Exchanges", "Pools", "Services/gambling/old"
                # Use them as section markers
                low = text.lower()
                if any(k in low for k in [
                    "exchange", "pool", "service", "gambling", "old",
                    "historic", "darknet", "market", "mixer", "other"
                ]):
                    current_cat = text
        elif name == "a":
            href = el.get("href", "")
            m = re.match(r"^/wallet/([^/?#]+)/?$", href)
            if m:
                wallet = m.group(1)
                categories.setdefault(current_cat, [])
                if wallet not in categories[current_cat]:
                    categories[current_cat].append(wallet)

    # Also do a flat list as a fallback / sanity check
    all_links = sorted({
        m.group(1)
        for a in soup.find_all("a", href=True)
        for m in [re.match(r"^/wallet/([^/?#]+)/?$", a["href"])]
        if m
    })

    print(f"Categories found: {len(categories)}", flush=True)
    for cat, wallets in categories.items():
        print(f"  {cat}: {len(wallets)} wallets", flush=True)
    print(f"Total unique wallets (flat): {len(all_links)}", flush=True)

    out = {
        "categories": categories,
        "all_wallets": all_links,
    }
    with open("wallets.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print("Saved wallets.json", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr, flush=True)
        sys.exit(1)
