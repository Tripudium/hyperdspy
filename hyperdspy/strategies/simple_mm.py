from decimal import Decimal

from hyperdspy.models import AccountState, BookSnapshot, DesiredOrder, Order, Side, StrategyDecision
from hyperdspy.strategy import Strategy


class SimpleMarketMaker(Strategy):
    """A minimal symmetric market maker.

    Places bid and ask orders at a fixed spread around the mid price.
    Adjusts skew based on current inventory to reduce directional exposure.
    """

    def __init__(
        self,
        half_spread_bps: Decimal = Decimal("5"),
        order_size: Decimal = Decimal("0.001"),
        skew_factor_bps: Decimal = Decimal("1"),
    ):
        self.half_spread_bps = half_spread_bps
        self.order_size = order_size
        self.skew_factor_bps = skew_factor_bps

    def on_tick(
        self,
        coin: str,
        book: BookSnapshot | None,
        account: AccountState,
        open_orders: list[Order],
    ) -> StrategyDecision | None:
        if book is None or book.mid_price is None:
            return None

        mid = book.mid_price
        half_spread = mid * self.half_spread_bps / Decimal("10000")

        # Inventory skew: shift quotes away from current position direction
        skew = Decimal("0")
        position = account.positions.get(coin)
        if position and position.size != 0:
            skew = position.size * mid * self.skew_factor_bps / Decimal("10000")

        bid_price = mid - half_spread - skew
        ask_price = mid + half_spread - skew

        return StrategyDecision(
            coin=coin,
            desired_orders=[
                DesiredOrder(side=Side.BID, price=bid_price, size=self.order_size),
                DesiredOrder(side=Side.ASK, price=ask_price, size=self.order_size),
            ],
            cancel_all_first=True,
        )
