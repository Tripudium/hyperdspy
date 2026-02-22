# Configuration Reference

All configuration is loaded from `config.json` in the project root. This file is gitignored to protect credentials.

## Full Example

```json
{
    "secret_key": "0xYOUR_PRIVATE_KEY",
    "account_address": "0xYOUR_WALLET_ADDRESS",
    "vault_address": null,

    "base_url": "https://api.hyperliquid.xyz",
    "paper_mode": true,
    "log_level": "INFO",
    "tick_interval_s": 1.0,

    "coins": ["BTC", "ETH"],
    "leverage": 20,
    "is_cross": true,
    "max_position_usd": 1000.0,

    "l4_server_url": "ws://localhost:8000/ws",

    "recording": {
        "enabled": true,
        "output_dir": "data",
        "format": "jsonl",
        "record_l2": true,
        "record_l4": true,
        "record_trades": true
    }
}
```

## Field Reference

### Wallet (required)

| Field | Type | Description |
|---|---|---|
| `secret_key` | string | Hyperliquid wallet private key (hex, `0x` prefix) |
| `account_address` | string | Wallet address (hex, `0x` prefix) |
| `vault_address` | string? | Vault address for vault trading (optional) |

### Network

| Field | Type | Default | Description |
|---|---|---|---|
| `base_url` | string | `https://api.hyperliquid.xyz` | API endpoint. Use `https://api.hyperliquid-testnet.xyz` for testnet |
| `paper_mode` | bool | `false` | `true` = simulate execution locally against live book data |

### Engine

| Field | Type | Default | Description |
|---|---|---|---|
| `tick_interval_s` | float | `1.0` | Seconds between strategy ticks |
| `log_level` | string | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

### Trading

| Field | Type | Default | Description |
|---|---|---|---|
| `coins` | list[str] | `["BTC"]` | Coins to trade (e.g., `["BTC", "ETH", "SOL"]`) |
| `leverage` | int | `20` | Default leverage (1-50x) |
| `is_cross` | bool | `true` | `true` = cross margin, `false` = isolated |
| `max_position_usd` | float | `1000.0` | Maximum position size in USD (risk limit) |

### L4 Data (optional)

| Field | Type | Default | Description |
|---|---|---|---|
| `l4_server_url` | string? | `null` | WebSocket URL of a Hyperliquid `order_book_server` instance |

L4 provides individual order-level data (oid, wallet address, price, size) and requires running your own [order_book_server](https://github.com/hyperliquid-dex/order_book_server) or using a hosted provider.

### Recording (optional)

| Field | Type | Default | Description |
|---|---|---|---|
| `recording.enabled` | bool | `false` | Enable data recording to disk |
| `recording.output_dir` | string | `data` | Output directory for recorded data |
| `recording.format` | string | `jsonl` | File format: `jsonl` (JSON lines) or `csv` |
| `recording.record_l2` | bool | `true` | Record L2 order book snapshots |
| `recording.record_l4` | bool | `true` | Record L4 data (requires `l4_server_url`) |
| `recording.record_trades` | bool | `true` | Record trade events |

## Minimal Config

The simplest valid config for paper trading:

```json
{
    "secret_key": "0xYOUR_PRIVATE_KEY",
    "account_address": "0xYOUR_WALLET_ADDRESS",
    "paper_mode": true
}
```

This will trade BTC with default settings in paper mode.

## Testnet

To use Hyperliquid's testnet:

```json
{
    "secret_key": "0xYOUR_TESTNET_KEY",
    "account_address": "0xYOUR_TESTNET_ADDRESS",
    "base_url": "https://api.hyperliquid-testnet.xyz",
    "paper_mode": false
}
```
