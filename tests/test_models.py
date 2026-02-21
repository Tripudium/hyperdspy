from decimal import Decimal

from hyperdspy.models import BookSnapshot, Fill, Order, OrderStatus, PriceLevel, Side


class TestPriceLevel:
    def test_from_sdk(self):
        raw = {"px": "67500.0", "sz": "1.5", "n": 3}
        level = PriceLevel.from_sdk(raw)
        assert level.price == Decimal("67500.0")
        assert level.size == Decimal("1.5")
        assert level.num_orders == 3


class TestBookSnapshot:
    def test_from_sdk(self, sample_sdk_l2_data):
        book = BookSnapshot.from_sdk(sample_sdk_l2_data)
        assert book.coin == "BTC"
        assert book.timestamp_ms == 1700000000000
        assert len(book.bids) == 3
        assert len(book.asks) == 3
        assert book.bids[0].price == Decimal("67500.0")
        assert book.asks[0].price == Decimal("67510.0")

    def test_mid_price(self, sample_book):
        assert sample_book.mid_price == Decimal("67505.0")

    def test_spread(self, sample_book):
        assert sample_book.spread == Decimal("10.0")

    def test_spread_bps(self, sample_book):
        bps = sample_book.spread_bps
        assert bps is not None
        # 10 / 67505 * 10000 ≈ 1.48
        assert Decimal("1.4") < bps < Decimal("1.5")

    def test_empty_book(self):
        book = BookSnapshot(coin="BTC", bids=(), asks=(), timestamp_ms=0)
        assert book.mid_price is None
        assert book.spread is None
        assert book.spread_bps is None


class TestFill:
    def test_from_sdk(self, sample_sdk_fill):
        fill = Fill.from_sdk(sample_sdk_fill)
        assert fill.coin == "BTC"
        assert fill.side == Side.BID
        assert fill.price == Decimal("67500.0")
        assert fill.size == Decimal("0.001")
        assert fill.oid == 12345
        assert fill.fee == Decimal("0.01")
        assert fill.is_crossed is False


class TestOrder:
    def test_properties(self):
        order = Order(
            coin="BTC",
            side=Side.BID,
            price=Decimal("67500"),
            size=Decimal("0.1"),
            order_type={"limit": {"tif": "Gtc"}},
        )
        assert order.is_buy is True
        assert order.remaining_size == Decimal("0.1")
        assert order.is_terminal is False

        order.status = OrderStatus.FILLED
        assert order.is_terminal is True

    def test_ask_side(self):
        order = Order(
            coin="ETH",
            side=Side.ASK,
            price=Decimal("3000"),
            size=Decimal("1.0"),
            order_type={"limit": {"tif": "Gtc"}},
        )
        assert order.is_buy is False
