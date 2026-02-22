from __future__ import annotations

import time
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Optional


class Side(Enum):
    BID = "B"
    ASK = "A"


class OrderStatus(Enum):
    PENDING = "pending"
    OPEN = "open"
    PARTIALLY_FILLED = "partial"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


@dataclass(frozen=True)
class PriceLevel:
    """A single price level in the L2 order book."""

    price: Decimal
    size: Decimal
    num_orders: int

    @staticmethod
    def from_sdk(raw: dict) -> PriceLevel:
        return PriceLevel(price=Decimal(raw["px"]), size=Decimal(raw["sz"]), num_orders=raw["n"])


@dataclass(frozen=True)
class BookSnapshot:
    """Point-in-time snapshot of the L2 order book for a single coin."""

    coin: str
    bids: tuple[PriceLevel, ...]  # Best (highest) first
    asks: tuple[PriceLevel, ...]  # Best (lowest) first
    timestamp_ms: int

    @property
    def mid_price(self) -> Optional[Decimal]:
        if self.bids and self.asks:
            return (self.bids[0].price + self.asks[0].price) / 2
        return None

    @property
    def spread(self) -> Optional[Decimal]:
        if self.bids and self.asks:
            return self.asks[0].price - self.bids[0].price
        return None

    @property
    def spread_bps(self) -> Optional[Decimal]:
        mid = self.mid_price
        if mid and mid > 0 and self.spread is not None:
            return (self.spread / mid) * 10_000
        return None

    @staticmethod
    def from_sdk(data: dict) -> BookSnapshot:
        """Convert SDK L2BookData to BookSnapshot.

        SDK format: {"coin": str, "levels": [[bids...], [asks...]], "time": int}
        """
        bids = tuple(PriceLevel.from_sdk(lvl) for lvl in data["levels"][0])
        asks = tuple(PriceLevel.from_sdk(lvl) for lvl in data["levels"][1])
        return BookSnapshot(coin=data["coin"], bids=bids, asks=asks, timestamp_ms=data["time"])


@dataclass
class Order:
    """Internal order representation tracking full lifecycle."""

    coin: str
    side: Side
    price: Decimal
    size: Decimal
    order_type: dict
    reduce_only: bool = False
    cloid: Optional[str] = None
    oid: Optional[int] = None
    status: OrderStatus = OrderStatus.PENDING
    filled_size: Decimal = Decimal("0")
    created_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    updated_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))

    @property
    def is_buy(self) -> bool:
        return self.side == Side.BID

    @property
    def remaining_size(self) -> Decimal:
        return self.size - self.filled_size

    @property
    def is_terminal(self) -> bool:
        return self.status in (OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED)


@dataclass(frozen=True)
class Fill:
    """A single fill event."""

    coin: str
    side: Side
    price: Decimal
    size: Decimal
    oid: int
    fee: Decimal
    timestamp_ms: int
    closed_pnl: Decimal
    is_crossed: bool

    @staticmethod
    def from_sdk(raw: dict) -> Fill:
        return Fill(
            coin=raw["coin"],
            side=Side(raw["side"]),
            price=Decimal(raw["px"]),
            size=Decimal(raw["sz"]),
            oid=raw["oid"],
            fee=Decimal(raw.get("fee", "0")),
            timestamp_ms=raw["time"],
            closed_pnl=Decimal(raw.get("closedPnl", "0")),
            is_crossed=raw.get("crossed", True),
        )


@dataclass(frozen=True)
class Position:
    """Current position in a single coin."""

    coin: str
    size: Decimal  # Positive = long, negative = short
    entry_price: Decimal
    unrealized_pnl: Decimal
    leverage: int
    liquidation_price: Optional[Decimal]
    margin_used: Decimal


@dataclass(frozen=True)
class AccountState:
    """Snapshot of account state."""

    account_value: Decimal
    total_margin_used: Decimal
    withdrawable: Decimal
    positions: dict[str, Position]


@dataclass(frozen=True)
class DesiredOrder:
    """A single order that a strategy wants placed."""

    side: Side
    price: Decimal
    size: Decimal
    order_type: dict = field(default_factory=lambda: {"limit": {"tif": "Gtc"}})
    reduce_only: bool = False


@dataclass(frozen=True)
class StrategyDecision:
    """What a strategy wants to do -- a list of desired quotes."""

    coin: str
    desired_orders: list[DesiredOrder]
    cancel_all_first: bool = True


# --- L4 (individual order-level) types ---


@dataclass(frozen=True)
class L4Order:
    """A single individual order in the L4 order book."""

    oid: int
    user: str  # wallet address
    price: Decimal
    size: Decimal
    side: Side

    @staticmethod
    def from_raw(raw: dict, side: Side) -> L4Order:
        return L4Order(
            oid=raw["oid"],
            user=raw.get("user", ""),
            price=Decimal(raw["limitPx"]),
            size=Decimal(raw["sz"]),
            side=side,
        )


@dataclass(frozen=True)
class L4BookSnapshot:
    """Full L4 order book state for a single coin.

    Unlike L2 which aggregates by price level, L4 shows every individual order
    with its owner's wallet address. Requires a Hyperliquid order_book_server.
    """

    coin: str
    bids: dict[Decimal, tuple[L4Order, ...]]  # price -> orders at that level
    asks: dict[Decimal, tuple[L4Order, ...]]
    timestamp_ms: int

    @property
    def best_bid(self) -> Optional[Decimal]:
        return max(self.bids.keys()) if self.bids else None

    @property
    def best_ask(self) -> Optional[Decimal]:
        return min(self.asks.keys()) if self.asks else None

    @property
    def mid_price(self) -> Optional[Decimal]:
        bb, ba = self.best_bid, self.best_ask
        if bb is not None and ba is not None:
            return (bb + ba) / 2
        return None

    @property
    def total_bid_size(self) -> Decimal:
        return sum((o.size for orders in self.bids.values() for o in orders), Decimal("0"))

    @property
    def total_ask_size(self) -> Decimal:
        return sum((o.size for orders in self.asks.values() for o in orders), Decimal("0"))
