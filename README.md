# Bitcoin Sentinel 🛡️

**Real-time Bitcoin fraud, scam, and money laundering detection system** using WebSockets.

Bitcoin Sentinel will stream live transactions from the Bitcoin network and analyze them against clusters of known suspicious wallets, scam addresses, sanctioned entities, and high-risk clusters — without requiring a full blockchain sync.

### Vision

Give independent auditors, law enforcement, compliance teams, and blockchain investigators a powerful, real-time tool to monitor suspicious Bitcoin activity as it happens.

- No full blockchain required — only pivot addresses with flags
- Smart storage: inactive clean addresses = zero disk usage
- High precision through exchange wallet intelligence
- Designed for real investigative use (fast, accurate, lightweight)

### Perfect For
- Independent Blockchain Investigators
- Government & Law Enforcement Agencies
- AML / Compliance Teams
- Crypto Security Researchers

---

## Current State

The project is in the **data collection and standardization phase**. The core runtime (WebSocket streaming, live classification) is not yet implemented.

### What is built: Data Pipeline (`wallets_flag_list/`)

Over **1 GB of flagged wallet data** has already been collected across two pipelines:

**Scam list** (`wallets_flag_list/scam_list_1/`):
- `download_scam_reports.py` — downloads all scam reports from the CheckCryptoAddress.com API (paginated, 16 parallel workers, rotating proxy, auto-retry). Output: `scam_reports_all.json`.

**Exchange allowlist** (`wallets_flag_list/exchange_list/`):
- `01_get_wallet_list.py` — scrapes WalletExplorer.com, extracts wallet names grouped by category (Exchanges, Pools, Services, Gambling, etc.), saves `wallets.json`.
- `02_download_csvs.py` — for each wallet in `wallets.json`, downloads all addresses as CSV into `csvs/<Category>/<wallet>.csv`. Already contains 100+ exchanges (Binance, Kraken, Bitfinex, Bitstamp, FoxBit, MercadoBitcoin, and more).

```
wallets_flag_list/
├── scam_list_1/
│   └── download_scam_reports.py   # scam addresses ← CheckCryptoAddress.com
└── exchange_list/
    ├── 01_get_wallet_list.py      # scrape WalletExplorer → wallets.json
    ├── 02_download_csvs.py        # download per-exchange address CSVs
    ├── wallets.json               # wallet index by category
    └── csvs/                      # 100+ exchange address lists
```

> The exchange list is used exclusively to **filter out false positives**: any address known to belong to a legitimate exchange is excluded from fraud alerts.

### Main Data Sources (collected so far)

- **OFAC SDN List** (April 2016 + ongoing updates)
- **[CheckCryptoAddress.com Scam Wallets](https://checkcryptoaddress.com/scam-wallets)** (Donations: bc1qs9vkrl0kahyynr9vn2m25r3e654zp59hwtq8m4)
- **[BitcoinWhoIsWho.com](https://www.bitcoinwhoswho.com/)** (Donations: 1MX96CwmUJABMwAiU4PjSxjm1Avr2cDHPd)
- **[Mempool Data](https://mempool.lyberry.com/)** — self-hosted mempool explorer
- Custom curated clusters from public investigations and community sources
- WalletExplorer exchange wallet database (for false positive reduction)

---

## Roadmap

### Next: Data Enrichment & Standardization
- Integrate with **Chainalysis**, **Crystal Blockchain**, and other intelligence providers to enrich collected addresses with risk scores, entity labels, and cluster metadata
- Standardize all collected data into a unified schema before ingestion

### Graph Risk Engine (Neo4j)
- Load standardized wallet data into a **Neo4j** graph database
- Model wallet-to-wallet relationships across multiple addresses and clusters
- Enable multi-hop risk scoring: evaluate the risk of an address based on its transaction graph neighborhood, not just a direct match

### Real-Time WebSocket Engine
- Connect to multiple Bitcoin/blockchain data providers via WebSocket (mempool feeds, block streams)
- This will enable **multichain real-time scanning** — providers and chains are still being evaluated
- Live classification engine: distinguishes exchanges, legitimate users, and high-risk entities as transactions arrive

### Planned Detection Capabilities (once runtime is live)
- **True Real-Time Monitoring** — mempool + confirmed blocks
- **Intelligent Address Clustering** — scam groups, ransomware, tumblers, darknet markets
- **Exchange Wallet Filtering** — WalletExplorer-based false positive reduction
- **Lightweight Storage** — only flagged/pivot addresses stored; clean addresses use zero disk space

---

**Status:** In Development (Data Collection Phase)  
**Primary Language:** Python (data pipeline) / NodeJS (runtime, planned)  
**License:** AGPL-3.0
