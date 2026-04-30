# Bitcoin Sentinel 🛡️

**Real-time Bitcoin fraud and scam detection engine** powered by WebSockets.

Bitcoin Sentinel monitors the Bitcoin network in real time, analysing every new
transaction against clusters of known suspicious wallets, scam addresses, mixing
services, and high-risk entities.  Exchange wallet intelligence (via
WalletExplorer) drastically reduces false positives.

---

## Key Features

| Feature | Description |
|---------|-------------|
| **Real-time Monitoring** | WebSocket connection to Blockchain.com's live transaction feed |
| **Smart Address Clustering** | Groups scam wallets, ransomware families, darknet markets, and mixing services |
| **Exchange Wallet Intelligence** | WalletExplorer integration suppresses exchange hot-wallet noise |
| **Lightweight Database** | SQLite — only *flagged* (pivot) addresses are stored; clean addresses consume zero space |
| **Risk Scoring** | 0-100 composite score combining cluster intelligence + on-chain heuristics |
| **Heuristics Engine** | Detects dust attacks, CoinJoin patterns, high-fanout payouts, round-number outputs |
| **JSON output mode** | Machine-readable `--json` flag for SIEM / log-aggregation pipelines |
| **Low resource footprint** | No need to store the full blockchain |

---

## Architecture

```
Bitcoin Network (WebSocket)
        │
        ▼
  sentinel/monitor.py        ← real-time WebSocket consumer + reconnect logic
        │
        ▼
  sentinel/classifier.py     ← composite risk scoring engine
     ├── sentinel/clusters.py          ← in-memory address cluster index (O(1) lookup)
     └── sentinel/exchange_filter.py   ← WalletExplorer integration (cached)
        │
        ▼
  sentinel/alerts.py         ← human-readable / JSON-lines alert output
        │
        ▼
  sentinel/database.py       ← SQLite: addresses · clusters · alerts
```

---

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
# or
pip install -e .
```

### 2. Start monitoring

```bash
python main.py
```

The engine connects to the live Bitcoin WebSocket feed, loads the seed address
database, and prints colour-coded alerts whenever a suspicious transaction is
seen.

### 3. Common options

```bash
# Lower alert threshold (fire on medium-risk too)
python main.py --threshold 50

# Machine-readable JSON output (SIEM-friendly)
python main.py --json

# Use a custom database / seed file
python main.py --db /var/lib/sentinel/prod.db --seed /etc/sentinel/addresses.json

# Disable exchange-wallet filter (not recommended — increases false positives)
python main.py --no-exchange-filter

# Show loaded clusters
python main.py --list-clusters

# Review recent alerts
python main.py --list-alerts 50
```

### 4. Environment variable overrides

| Variable | Default | Description |
|----------|---------|-------------|
| `SENTINEL_DB_PATH` | `data/sentinel.db` | SQLite database path |
| `SENTINEL_KNOWN_ADDRESSES_FILE` | `data/known_addresses.json` | Seed data path |
| `SENTINEL_BTC_WS_URL` | `wss://ws.blockchain.info/inv` | WebSocket feed |
| `SENTINEL_RISK_THRESHOLD` | `61` | Alert threshold (0-100) |
| `SENTINEL_LOG_LEVEL` | `INFO` | Log verbosity |
| `SENTINEL_WALLET_CACHE_TTL` | `86400` | WalletExplorer cache TTL (seconds) |

---

## Risk Levels

| Score | Level | Meaning |
|-------|-------|---------|
| 0 – 30 | **CLEAN** | No suspicious signals |
| 31 – 60 | **LOW** | Minor indicators — monitor |
| 61 – 80 | **MEDIUM** | Significant indicators — review |
| 81 – 100 | **HIGH** | Confirmed / known malicious |

---

## Address Seed Data (`data/known_addresses.json`)

The seed file contains publicly documented Bitcoin addresses from:

- **OFAC SDN List** — sanctioned entities (Lazarus Group / DPRK)
- **US DOJ / FBI indictments** — Silk Road, AlphaBay, Bitfinex hack
- **US-CERT advisories** — WannaCry, CryptoLocker ransomware
- **Europol / FBI joint operations** — ChipMixer mixing service
- **Academic blockchain forensics** — PlusToken, OneCoin

Exchange addresses (Binance, Coinbase, Kraken, …) are included with low risk
scores so the classifier can suppress false positives without calling
WalletExplorer for every transaction.

### Extending the seed data

Add a new cluster to `data/known_addresses.json`:

```json
{
  "id": "my_new_cluster",
  "name": "My New Threat Cluster",
  "category": "RANSOMWARE",
  "description": "Source: ...",
  "confidence": 90,
  "addresses": [
    { "address": "1XxxYyyZzz...", "risk_score": 92, "notes": "..." }
  ]
}
```

Supported categories: `RANSOMWARE` · `DARKNET` · `SCAM` · `FRAUD` · `MIXER` ·
`SANCTIONS` · `EXCHANGE`

---

## Heuristics

Beyond exact address matching, Sentinel flags transactions that exhibit known
obfuscation patterns:

| Heuristic | Description |
|-----------|-------------|
| `DUST_OUTPUTS` | ≥ 3 outputs ≤ 546 satoshis (dust attack) |
| `EQUAL_OUTPUTS_MIXING` | ≥ 5 outputs with identical values (CoinJoin) |
| `ROUND_NUMBER_OUTPUT` | Single non-dust output that is a whole BTC multiple |
| `HIGH_FANOUT` | Output count ≥ 10× input count (mixer payout) |

Each active heuristic adds up to +10 points (max +30) to the composite score.

---

## Project Structure

```
Bitcoin-Sentinel-Real-Time-Fraud-Scam-Detector/
├── sentinel/
│   ├── __init__.py
│   ├── config.py           # Configuration (env-var overridable)
│   ├── database.py         # SQLite layer — addresses, clusters, alerts
│   ├── clusters.py         # Address clustering + in-memory index
│   ├── exchange_filter.py  # WalletExplorer integration + local cache
│   ├── classifier.py       # Transaction risk scoring engine
│   ├── monitor.py          # WebSocket consumer + reconnect logic
│   └── alerts.py           # Alert formatting (human + JSON)
├── data/
│   └── known_addresses.json  # Seed data (public threat intelligence)
├── tests/
│   ├── test_database.py
│   ├── test_clusters.py
│   └── test_classifier.py
├── main.py                 # CLI entry point
├── requirements.txt
└── setup.py
```

---

## Running Tests

```bash
pip install pytest pytest-asyncio
pytest tests/ -v
```

---

## Target Users

- Independent Blockchain Investigators
- Government & Law Enforcement Agencies
- Crypto Compliance Teams (AML/CFT)
- Security Researchers
- AML (Anti-Money Laundering) Specialists

---

## Status

**MVP ready** — core engine implemented in Python (asyncio + websockets).

Planned improvements:
- REST API / web dashboard
- Tor exit-node address list integration
- OFAC SDN automated sync
- Rust-based high-throughput address lookup module
- Webhook / Slack / PagerDuty alert delivery

---

## License

Apache License 2.0 — see [LICENSE](LICENSE).