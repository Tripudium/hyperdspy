from abc import ABC, abstractmethod

from hyperdspy.models import AccountState, BookSnapshot, Fill, Order, StrategyDecision


class Strategy(ABC):
    """Base class for market making strategies.

    The engine calls on_tick() at a regular interval. The strategy receives
    current market state and returns a StrategyDecision describing what orders
    it wants to have on the book.

    The strategy does NOT place orders directly. It returns desired state,
    and the engine reconciles current orders with desired orders.
    """

    @abstractmethod
    def on_tick(
        self,
        coin: str,
        book: BookSnapshot | None,
        account: AccountState,
        open_orders: list[Order],
    ) -> StrategyDecision | None:
        """Called each tick with current state. Return desired orders or None to skip.

        Args:
            coin: The coin this tick is for.
            book: Latest L2 order book snapshot (None if no data yet).
            account: Current account state (balances, positions).
            open_orders: Orders currently open for this coin.

        Returns:
            StrategyDecision describing desired orders, or None to take no action.
        """
        ...

    def on_fill(self, fill: Fill) -> None:
        """Optional callback when one of our orders is filled. Default: no-op."""

    def on_start(self, coins: list[str]) -> None:
        """Called once when the engine starts. Override for initialization."""

    def on_stop(self) -> None:
        """Called when the engine shuts down. Override for cleanup."""
