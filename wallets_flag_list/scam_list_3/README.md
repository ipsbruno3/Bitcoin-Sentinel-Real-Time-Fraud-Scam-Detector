# scam_list_3 — EVM On-Chain Banned Addresses (USDC / USDT)

## What this data is

`banned_addresses_unified.json` contains addresses that have been **officially blacklisted at the smart contract level** by the issuers of the two largest stablecoins on the Ethereum EVM:

| Token | Issuer | Contract action |
|-------|--------|----------------|
| USDC  | Circle (Centre) | `blacklist(address)` on the USDC ERC-20 contract |
| USDT  | Tether | `addBlackList(address)` on the USDT ERC-20 contract |

Once blacklisted, the address **cannot transfer or receive** the token. The ban is enforced on-chain — it is not advisory. These are the hardest possible flags in the EVM ecosystem: the issuer permanently froze those funds.

## Schema

```json
{
  "address":     "0xde787f609e...",   // banned EVM address (0x-prefixed, 40 hex chars)
  "tokenstring": "0xa0b86991c6...",   // token contract address
  "txhash":      "0xabc123...",       // transaction hash that executed the ban
  "timestamp":   1745534255,          // Unix epoch of the ban transaction
  "symbol":      "USDC",             // "USDC" or "USDT"
  "label":       "blacklisted"        // ban status label
}
```

## Coverage

~2,194 unique addresses across USDC and USDT bans, sourced from on-chain event logs via [tokenview.io](https://tokenview.io).

## How to refresh

```bash
python download_banned_addresses.py
```

Outputs: `banned_addresses_unified.json`

## Role in Bitcoin Sentinel

Although Bitcoin Sentinel focuses on the Bitcoin network, EVM-banned addresses are valuable for **cross-chain entity correlation**: an address banned by Tether or Circle is a confirmed sanctioned/fraudulent entity, and the same entity often controls Bitcoin wallets. This list enriches cluster attribution when correlating on-chain intelligence across chains.
