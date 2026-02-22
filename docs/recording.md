# Data Recording

HyperDSPY can record L2 order book snapshots, L4 individual-order data, and trades to disk for later analysis and backtesting.

## Quick Setup

Add to `config.json`:

```json
{
    "recording": {
        "enabled": true,
        "output_dir": "data",
        "format": "jsonl"
    }
}
```

Then run the engine. Data files will appear in `data/{coin}/`.

## File Layout

```
data/
  BTC/
    l2_2026-02-22.jsonl       # L2 order book snapshots
    trades_2026-02-22.jsonl   # Trade events
    l4_2026-02-22.jsonl       # L4 data (if l4_server_url configured)
  ETH/
    l2_2026-02-22.jsonl
    trades_2026-02-22.jsonl
```

Files rotate automatically at midnight UTC.

## L2 Record Format (JSON Lines)

Each line is a JSON object:

```json
{
    "recv_ts_ms": 1700000000123,
    "exch_ts_ms": 1700000000100,
    "coin": "BTC",
    "best_bid": "67500.0",
    "best_bid_sz": "1.5",
    "best_ask": "67510.0",
    "best_ask_sz": "1.2",
    "mid": "67505.0",
    "spread_bps": "1.48",
    "bid_levels": 10,
    "ask_levels": 10,
    "bids": [{"px": "67500.0", "sz": "1.5", "n": 3}, ...],
    "asks": [{"px": "67510.0", "sz": "1.2", "n": 4}, ...]
}
```

| Field | Description |
|---|---|
| `recv_ts_ms` | Local receive timestamp (ms) |
| `exch_ts_ms` | Exchange timestamp (ms) |
| `best_bid` / `best_ask` | Top-of-book prices |
| `mid` | Mid price |
| `spread_bps` | Spread in basis points |
| `bids` / `asks` | Full depth: price, size, number of orders per level |

## Trade Record Format

```json
{
    "recv_ts_ms": 1700000001000,
    "coin": "BTC",
    "side": "B",
    "px": "67505.0",
    "sz": "0.5",
    "time": 1700000001000,
    "hash": "0xabc..."
}
```

| Field | Description |
|---|---|
| `side` | `"B"` (buy/bid) or `"A"` (sell/ask) -- the taker's side |
| `px` | Trade price |
| `sz` | Trade size |
| `hash` | Transaction hash |

## L4 Record Format

L4 records preserve the raw message from the order\_book\_server, wrapped with a receive timestamp:

```json
{
    "recv_ts_ms": 1700000000500,
    "coin": "BTC",
    "data": {
        "coin": "BTC",
        "bids": [{"oid": 42, "user": "0xabc...", "limitPx": "67500.0", "sz": "1.5"}, ...],
        "asks": [...]
    }
}
```

The `data` field is either a full snapshot (first message) or a block-batched diff (subsequent messages).

## CSV Format

Set `"format": "csv"` to write flattened CSV files. This works best for L2 top-of-book and trade data. The full depth arrays are serialized as strings in CSV mode.

## Loading Data for Analysis

### With pandas

```python
import pandas as pd

# Load L2 data
l2 = pd.read_json("data/BTC/l2_2026-02-22.jsonl", lines=True)
l2["recv_ts"] = pd.to_datetime(l2["recv_ts_ms"], unit="ms")
print(l2[["recv_ts", "mid", "spread_bps"]].head())

# Load trades
trades = pd.read_json("data/BTC/trades_2026-02-22.jsonl", lines=True)
```

### With polars

```python
import polars as pl

l2 = pl.read_ndjson("data/BTC/l2_2026-02-22.jsonl")
```

## Selective Recording

You can enable/disable each data type independently:

```json
{
    "recording": {
        "enabled": true,
        "record_l2": true,
        "record_l4": false,
        "record_trades": true
    }
}
```

## L4 Data Requirements

L4 recording requires:

1. A running Hyperliquid `order_book_server` (Rust binary) connected to a non-validating node
2. Set `"l4_server_url": "ws://localhost:8000/ws"` in config.json

See the [order_book_server repo](https://github.com/hyperliquid-dex/order_book_server) for setup instructions.

Without `l4_server_url`, L4 recording is silently skipped even if `record_l4` is `true`.
