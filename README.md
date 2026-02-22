# HyperDSPY

A Python framework for algorithmic trading on [Hyperliquid](https://hyperliquid.xyz). Stream real-time order book data, place orders, and test market making strategies with built-in paper trading.

## Features

- **Real-time L2 order book streaming** via WebSocket with thread-safe state management
- **L4 order-level data** (individual orders with wallet addresses) via Hyperliquid's order\_book\_server
- **Order management** with full lifecycle tracking (place, modify, cancel, fill reconciliation)
- **Strategy framework** -- define strategies as desired-state declarations, the engine handles reconciliation
- **Paper trading** -- test strategies against live market data without risking capital
- **Data recording** -- record L2 books, L4 data, and trades to JSON lines or CSV for backtesting

## Requirements

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) package manager

## Installation

```bash
git clone <repo-url>
cd hyperdspy
uv sync
```

## Configuration

Create a `config.json` in the project root (this file is gitignored):

```json
{
    "secret_key": "0xYOUR_PRIVATE_KEY",
    "account_address": "0xYOUR_WALLET_ADDRESS",
    "paper_mode": true,
    "coins": ["BTC", "ETH"],
    "tick_interval_s": 1.0
}
```

**Required fields:** `secret_key`, `account_address`

See [docs/configuration.md](docs/configuration.md) for all available options.

## Quick Start

Run the built-in simple market maker in paper mode:

```bash
uv run dspy
```

Or use the framework programmatically:

```python
from decimal import Decimal
from hyperdspy.config import load_config
from hyperdspy.engine import Engine
from hyperdspy.strategies.simple_mm import SimpleMarketMaker

config = load_config()
strategy = SimpleMarketMaker(half_spread_bps=Decimal("10"), order_size=Decimal("0.001"))
engine = Engine(config, strategy)
engine.run()  # Ctrl-C to stop
```

## Writing a Custom Strategy

Subclass `Strategy` and implement `on_tick()`:

```python
from decimal import Decimal
from hyperdspy.strategy import Strategy
from hyperdspy.models import (
    BookSnapshot, AccountState, Order, StrategyDecision, DesiredOrder, Side,
)

class MyStrategy(Strategy):
    def on_tick(self, coin, book, account, open_orders):
        if book is None or book.mid_price is None:
            return None

        mid = book.mid_price
        offset = mid * Decimal("0.001")  # 10 bps

        return StrategyDecision(
            coin=coin,
            desired_orders=[
                DesiredOrder(side=Side.BID, price=mid - offset, size=Decimal("0.001")),
                DesiredOrder(side=Side.ASK, price=mid + offset, size=Decimal("0.001")),
            ],
        )
```

See [docs/strategies.md](docs/strategies.md) for a full walkthrough.

## Data Recording

Enable recording in `config.json` to capture market data for analysis:

```json
{
    "recording": {
        "enabled": true,
        "output_dir": "data",
        "format": "jsonl"
    }
}
```

Files are written to `data/{coin}/{type}_{date}.jsonl` with daily rotation. See [docs/recording.md](docs/recording.md) for details.

## Development

```bash
uv sync --dev              # Install dev dependencies
uv run pytest              # Run tests
uv run ruff check .        # Lint
uv run ruff format .       # Format
uv run jupyter lab         # Launch Jupyter for experimentation
```

## Documentation

- [Architecture Overview](docs/architecture.md) -- system design, data flow, threading model
- [Configuration Reference](docs/configuration.md) -- all config.json options
- [Strategy Guide](docs/strategies.md) -- writing and testing custom strategies
- [Data Recording](docs/recording.md) -- L2/L4/trade recording and replay
- [Use Case: Market Making](docs/use-case-market-making.md) -- end-to-end walkthrough

## Project Structure

```
hyperdspy/
    __init__.py          # Entry point (uv run dspy)
    config.py            # Configuration loading
    models.py            # Domain types (BookSnapshot, Order, Fill, etc.)
    orderbook.py         # Thread-safe L2 order book state
    gateway.py           # SDK facade (Info + Exchange)
    order_manager.py     # Order lifecycle tracking
    strategy.py          # Strategy base class
    paper.py             # Paper trading backend
    engine.py            # Main orchestrator
    l4_client.py         # L4 order book WebSocket client
    recorder.py          # Data recording to disk
    strategies/
        simple_mm.py     # Example market maker
tests/                   # Unit tests
examples/                # Jupyter notebooks
docs/                    # Documentation
```
