# Sanctions Crypto Address Lists

Aggregated wallet addresses sanctioned by global authorities. Two sources cover ~99% of all published crypto sanctions:

- **OFAC (US Treasury)** via [0xB10C/ofac-sanctioned-digital-currency-addresses](https://github.com/0xB10C/ofac-sanctioned-digital-currency-addresses)
- **Israel MOD crypto sanctions** via [OpenSanctions `il_mod_crypto`](https://www.opensanctions.org/datasets/il_mod_crypto/)

UK FCDO, EU FSF, and UN SC publish almost no crypto wallet addresses (their sanctions target people/entities/vessels), so they are intentionally not included here.

## Layout

| Path | Contents |
|---|---|
| `ofac/` | Per-coin TXT + JSON, 17 coins (ARB, BCH, BSC, BSV, BTG, DASH, ETC, ETH, LTC, TRX, USDC, USDT, XBT, XMR, XRP, XVG, ZEC) |
| `opensanctions/il_mod_crypto.*` | Israel MOD crypto sanctions (CSV + NDJSON) |
| `combined/<COIN>.txt` | Final merged + deduplicated addresses, one per line |
| `combined/all_addresses.txt` | Every address across every coin |
| `combined/all_addresses_with_currency.tsv` | `address \t currency \t sources` |
| `combined/summary.txt` | Per-coin and per-source counts |
| `update.py` | Refresh script: downloads everything, then rebuilds `combined/` |

## Updating

```bash
python update.py            # download fresh + rebuild combined/
python update.py --no-fetch # rebuild combined/ from local files only
```

Total runtime ~5–10 seconds. ~3 MB on disk.

## Currency inference

When OpenSanctions ships a wallet without a `currency` property, `update.py` infers it by address format (BTC bech32/legacy, ETH 0x40hex, TRX T+34, LTC, XMR, DASH, ZEC-t, BCH cashaddr, XRP r-prefix). One il_mod_crypto entry contains Cyrillic look-alike chars and lands in `combined/UNKNOWN.txt`.

## Licensing

OpenSanctions data is free for non-commercial use; commercial use requires a license from opensanctions.org. The 0xB10C OFAC repo mirrors public US Treasury data.
