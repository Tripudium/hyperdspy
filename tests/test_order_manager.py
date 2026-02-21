from decimal import Decimal

from hyperdspy.models import DesiredOrder, Fill, OrderStatus, Side
from hyperdspy.order_manager import OrderManager


class FakeExecution:
    """Minimal execution backend for testing OrderManager."""

    def __init__(self):
        self._next_oid = 100
        self._cancelled: list[str] = []

    def place_order(self, coin, is_buy, sz, limit_px, order_type, reduce_only=False, cloid=None):
        oid = self._next_oid
        self._next_oid += 1
        return {
            "status": "ok",
            "response": {"type": "order", "data": {"statuses": [{"resting": {"oid": oid}}]}},
        }

    def place_bulk_orders(self, orders):
        statuses = []
        for _ in orders:
            oid = self._next_oid
            self._next_oid += 1
            statuses.append({"resting": {"oid": oid}})
        return {"status": "ok", "response": {"type": "order", "data": {"statuses": statuses}}}

    def cancel_order(self, coin, oid):
        return {"status": "ok"}

    def cancel_bulk(self, cancels):
        return {"status": "ok"}

    def cancel_all(self, coin):
        self._cancelled.append(coin)
        return {"status": "ok"}

    def get_open_orders(self):
        return []

    def get_user_state(self):
        return {"marginSummary": {"accountValue": "10000"}, "assetPositions": []}

    def get_user_fills(self):
        return []


class TestOrderManager:
    def test_place_order(self):
        om = OrderManager(FakeExecution())
        order = om.place_order("BTC", Side.BID, Decimal("67500"), Decimal("0.1"), {"limit": {"tif": "Gtc"}})

        assert order.coin == "BTC"
        assert order.side == Side.BID
        assert order.status == OrderStatus.OPEN
        assert order.oid is not None
        assert order.cloid is not None

    def test_place_bulk(self):
        om = OrderManager(FakeExecution())
        desired = [
            DesiredOrder(side=Side.BID, price=Decimal("67500"), size=Decimal("0.1")),
            DesiredOrder(side=Side.ASK, price=Decimal("67510"), size=Decimal("0.1")),
        ]
        orders = om.place_bulk("BTC", desired)

        assert len(orders) == 2
        assert orders[0].status == OrderStatus.OPEN
        assert orders[1].status == OrderStatus.OPEN
        assert orders[0].side == Side.BID
        assert orders[1].side == Side.ASK

    def test_get_open_orders(self):
        om = OrderManager(FakeExecution())
        om.place_order("BTC", Side.BID, Decimal("67500"), Decimal("0.1"), {"limit": {"tif": "Gtc"}})
        om.place_order("ETH", Side.ASK, Decimal("3000"), Decimal("1.0"), {"limit": {"tif": "Gtc"}})

        all_orders = om.get_open_orders()
        assert len(all_orders) == 2

        btc_orders = om.get_open_orders("BTC")
        assert len(btc_orders) == 1
        assert btc_orders[0].coin == "BTC"

    def test_cancel_all(self):
        fake = FakeExecution()
        om = OrderManager(fake)
        om.place_order("BTC", Side.BID, Decimal("67500"), Decimal("0.1"), {"limit": {"tif": "Gtc"}})
        om.place_order("BTC", Side.ASK, Decimal("67510"), Decimal("0.1"), {"limit": {"tif": "Gtc"}})

        om.cancel_all("BTC")

        assert len(om.get_open_orders("BTC")) == 0
        assert "BTC" in fake._cancelled

    def test_on_fill(self):
        om = OrderManager(FakeExecution())
        order = om.place_order("BTC", Side.BID, Decimal("67500"), Decimal("0.1"), {"limit": {"tif": "Gtc"}})

        fill = Fill(
            coin="BTC",
            side=Side.BID,
            price=Decimal("67500"),
            size=Decimal("0.1"),
            oid=order.oid,
            fee=Decimal("0.01"),
            timestamp_ms=1700000001000,
            closed_pnl=Decimal("0"),
            is_crossed=False,
        )
        om.on_fill(fill)

        assert order.status == OrderStatus.FILLED
        assert order.filled_size == Decimal("0.1")

    def test_partial_fill(self):
        om = OrderManager(FakeExecution())
        order = om.place_order("BTC", Side.BID, Decimal("67500"), Decimal("0.1"), {"limit": {"tif": "Gtc"}})

        fill = Fill(
            coin="BTC",
            side=Side.BID,
            price=Decimal("67500"),
            size=Decimal("0.05"),
            oid=order.oid,
            fee=Decimal("0.005"),
            timestamp_ms=1700000001000,
            closed_pnl=Decimal("0"),
            is_crossed=False,
        )
        om.on_fill(fill)

        assert order.status == OrderStatus.PARTIALLY_FILLED
        assert order.filled_size == Decimal("0.05")
        assert order.remaining_size == Decimal("0.05")

    def test_cleanup_terminal(self):
        om = OrderManager(FakeExecution())
        om.place_order("BTC", Side.BID, Decimal("67500"), Decimal("0.1"), {"limit": {"tif": "Gtc"}})
        om.cancel_all("BTC")

        # With max_age_ms=0, all terminal orders are cleaned up immediately
        om.cleanup_terminal(max_age_ms=0)
        assert len(om.get_open_orders()) == 0
