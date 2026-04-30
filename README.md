# Bitcoin Sentinel 🛡️

**Real-time Bitcoin fraud, scam, and money laundering detection system** using WebSockets.

Bitcoin Sentinel streams live transactions from the Bitcoin network and instantly analyzes them against clusters of known suspicious wallets, scam addresses, sanctioned entities, and high-risk clusters.

### Key Features

- **True Real-Time Monitoring** via Bitcoin WebSocket (mempool + blocks)
- **Intelligent Address Clustering** of scam groups, ransomware, tumblers, and darknet markets
- **Exchange Wallet Filtering** using WalletExplorer to minimize false positives
- **Extremely Lightweight Storage** — only pivot/flagged addresses are stored. Clean or inactive addresses (even from 2013) use zero disk space.
- **Live Classification** — distinguishes exchanges, legitimate users, and high-risk entities in real time

### Main Data Sources

- **OFAC SDN List** (April 2016 + ongoing updates)
- **[CheckCryptoAddress.com Scam Wallets](https://checkcryptoaddress.com/scam-wallets)** (Donations: bc1qs9vkrl0kahyynr9vn2m25r3e654zp59hwtq8m4)
- **[BitcoinWhoIsWho.com](https://www.bitcoinwhoswho.com/)** (Donations: 1MX96CwmUJABMwAiU4PjSxjm1Avr2cDHPd)
- **Mempool Data** — [mempool.lyberry.com](https://mempool.lyberry.com/) (https://github.com/mempool)
- Custom curated clusters from public investigations and community sources
- WalletExplorer exchange wallet database (for false positive reduction)

### Goal

Give independent auditors, law enforcement, compliance teams, and blockchain investigators a powerful, real-time tool to monitor suspicious Bitcoin activity as it happens — without needing to sync the entire blockchain.

### Main Differentiators

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

**Status:** In Development (MVP Ready)  
**Primary Language:** NodeJS  
**License:** AGPL-3.0

**Donation Address:** `No need, just enjoy the project and help build a larger ecosystem.
