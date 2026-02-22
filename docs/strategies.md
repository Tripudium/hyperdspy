# Strategy Guide

## How Strategies Work

A strategy is a class that receives market state and returns a **desired order state**. The engine handles the rest -- cancelling stale orders and placing new ones.

This is a key design decision: strategies declare _what orders should be on the book_, not _what actions to take_. This prevents bugs from strategies that forget to cancel outdated orders.

## The Strategy Interface

```python
from abc import ABC, abstractmethod
from hyperdspy.models import BookSnapshot, AccountState, Order, Fill, StrategyDecision

class Strategy(ABC):

    @abstractmethod
    def on_tick(
        self,
        coin: str,
        book: BookSnapshot | None,
        account: AccountState,
        open_orders: list[Order],
    ) -> StrategyDecision | None:
        """Called each tick. Return desired orders or None to skip."""
        ...

    def on_fill(self, fill: Fill) -> None:
        """Optional: called when one of our orders is filled."""

    def on_start(self, coins: list[str]) -> None:
        """Optional: called once when the engine starts."""

    def on_stop(self) -> None:
        """Optional: called when the engine shuts down."""
```

## on_tick Arguments

| Argument | Type | Description |
|---|---|---|
| `coin` | `str` | The coin this tick is for (e.g., `"BTC"`) |
| `book` | `BookSnapshot \| None` | Latest L2 order book. `None` if no data received yet |
| `account` | `AccountState` | Current account balances and positions |
| `open_orders` | `list[Order]` | Orders currently open for this coin |

### BookSnapshot Properties

```python
book.mid_price     # Decimal: (best_bid + best_ask) / 2
book.spread        # Decimal: best_ask - best_bid
book.spread_bps    # Decimal: spread in basis points
book.bids          # tuple[PriceLevel, ...]: sorted best-first
book.asks          # tuple[PriceLevel, ...]: sorted best-first
book.timestamp_ms  # int: exchange timestamp
```

Each `PriceLevel` has `price`, `size`, and `num_orders`.

### AccountState Fields

```python
account.account_value      # Decimal: total account value in USD
account.total_margin_used  # Decimal
account.withdrawable       # Decimal
account.positions          # dict[str, Position]: coin -> Position
```

Each `Position` has `size` (+long/-short), `entry_price`, `unrealized_pnl`, `leverage`, `liquidation_price`, `margin_used`.

## Returning a StrategyDecision

```python
from hyperdspy.models import StrategyDecision, DesiredOrder, Side

StrategyDecision(
    coin="BTC",
    desired_orders=[
        DesiredOrder(side=Side.BID, price=Decimal("67500"), size=Decimal("0.001")),
        DesiredOrder(side=Side.ASK, price=Decimal("67510"), size=Decimal("0.001")),
    ],
    cancel_all_first=True,  # Cancel existing orders before placing new ones
)
```

Return `None` to skip this tick (e.g., when book data isn't available yet).

### DesiredOrder Options

| Field | Type | Default | Description |
|---|---|---|---|
| `side` | `Side` | required | `Side.BID` (buy) or `Side.ASK` (sell) |
| `price` | `Decimal` | required | Limit price |
| `size` | `Decimal` | required | Order size in base currency |
| `order_type` | `dict` | `{"limit": {"tif": "Gtc"}}` | Order type. Options: `Gtc`, `Ioc`, `Alo` |
| `reduce_only` | `bool` | `False` | Only reduce existing position |

## Example: Spread Market Maker

This strategy places orders at a fixed spread around mid, with inventory skew:

```python
from decimal import Decimal
from hyperdspy.strategy import Strategy
from hyperdspy.models import (
    BookSnapshot, AccountState, Order,
    StrategyDecision, DesiredOrder, Side,
)

class SpreadMM(Strategy):
    def __init__(self, spread_bps=Decimal("10"), size=Decimal("0.001")):
        self.spread_bps = spread_bps
        self.size = size

    def on_tick(self, coin, book, account, open_orders):
        if book is None or book.mid_price is None:
            return None

        mid = book.mid_price
        half = mid * self.spread_bps / Decimal("20000")

        # Skew quotes away from inventory
        pos = account.positions.get(coin)
        skew = Decimal("0")
        if pos and pos.size != 0:
            skew = pos.size * mid * Decimal("0.0001")

        return StrategyDecision(
            coin=coin,
            desired_orders=[
                DesiredOrder(Side.BID, mid - half - skew, self.size),
                DesiredOrder(Side.ASK, mid + half - skew, self.size),
            ],
        )
```

## Example: Fill-Aware Strategy

Track fills for custom inventory management:

```python
from decimal import Decimal
from hyperdspy.strategy import Strategy
from hyperdspy.models import Fill, StrategyDecision, DesiredOrder, Side

class FillTracker(Strategy):
    def __init__(self):
        self.total_pnl = Decimal("0")
        self.fill_count = 0

    def on_fill(self, fill):
        self.fill_count += 1
        self.total_pnl += fill.closed_pnl
        print(f"Fill #{self.fill_count}: {fill.side.name} {fill.size} @ {fill.price} "
              f"| PnL: {self.total_pnl}")

    def on_tick(self, coin, book, account, open_orders):
        if book is None or book.mid_price is None:
            return None

        mid = book.mid_price
        offset = mid * Decimal("0.0005")

        return StrategyDecision(
            coin=coin,
            desired_orders=[
                DesiredOrder(Side.BID, mid - offset, Decimal("0.001")),
                DesiredOrder(Side.ASK, mid + offset, Decimal("0.001")),
            ],
        )

    def on_stop(self):
        print(f"Session complete: {self.fill_count} fills, PnL: {self.total_pnl}")
```

## Running Your Strategy

```python
from hyperdspy.config import load_config
from hyperdspy.engine import Engine

config = load_config()
engine = Engine(config)
engine.run(MyStrategy())
```

Or modify `hyperdspy/__init__.py` to use your strategy as the default.

## Testing with Paper Mode

Set `"paper_mode": true` in `config.json`. The engine streams real market data but simulates order execution locally:

- Resting limit orders fill when the book crosses their price
- Simulated positions and PnL are tracked
- The same `OrderManager` and `Strategy` code runs in both modes

This lets you validate strategy logic with realistic market dynamics before going live.
