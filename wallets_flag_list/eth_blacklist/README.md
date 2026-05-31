# eth_blacklist — EVM On-Chain Banned Addresses (USDC / USDT · Ethereum)

## What this data is

`banned_addresses_unified.json` contains addresses **officially blacklisted at the smart-contract level** by the two largest stablecoin issuers on Ethereum:

| Token | Issuer  | Contract event                  | Effect |
|-------|---------|---------------------------------|--------|
| USDC  | Circle  | `Blacklisted(address)`          | Address cannot send or receive USDC |
| USDT  | Tether  | `AddedBlackList(address)`       | Address cannot send or receive USDT |

These are the hardest possible flags in the EVM ecosystem. The ban is **enforced on-chain** — not advisory. Frozen funds cannot move.

## Schema

```json
{
  "address":   "0x072cc4898c...",   // banned EVM address (lowercase, 0x-prefixed)
  "symbol":    "USDC",              // "USDC" or "USDT"
  "txhash":    "0xabc123...",       // transaction that executed the ban
  "block":     19500000,            // Ethereum block number
  "timestamp": 1745534255,          // Unix epoch of the ban transaction
  "contract":  "0xa0b86991c6..."    // token contract address
}
```

## How to refresh

```bash
export ETHERSCAN_API_KEY=your_key_here   # free at etherscan.io/myapikey
export WEBSHARE_PROXY_URL=http://user:pass@p.webshare.io:80/   # optional

pip install requests web3
python download_banned_addresses.py
```

The script enumerates every `Blacklisted` / `AddedBlackList` event on Ethereum
mainnet from contract deployment (2017/2018) to the latest block, using the
Etherscan getLogs API with parallel chunked requests.

## Role in Bitcoin Sentinel

Although Bitcoin Sentinel focuses on Bitcoin, EVM-blacklisted addresses are
valuable for **cross-chain entity correlation**: an address banned by Tether
or Circle is a confirmed sanctioned/fraudulent entity. The same controlling
entity often operates Bitcoin wallets as well, enriching cluster attribution
across chains.
