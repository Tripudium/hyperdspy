from decimal import Decimal

from hyperdspy.models import L4BookSnapshot, L4Order, Side


class TestL4Order:
    def test_from_raw(self):
        raw = {"oid": 42, "user": "0xabc", "limitPx": "67500.0", "sz": "1.5"}
        order = L4Order.from_raw(raw, Side.BID)
        assert order.oid == 42
        assert order.user == "0xabc"
        assert order.price == Decimal("67500.0")
        assert order.size == Decimal("1.5")
        assert order.side == Side.BID

    def test_from_raw_no_user(self):
        raw = {"oid": 1, "limitPx": "3000.0", "sz": "10.0"}
        order = L4Order.from_raw(raw, Side.ASK)
        assert order.user == ""
        assert order.side == Side.ASK


class TestL4BookSnapshot:
    def test_properties(self):
        bid_order = L4Order(oid=1, user="0xa", price=Decimal("67500"), size=Decimal("1.0"), side=Side.BID)
        ask_order = L4Order(oid=2, user="0xb", price=Decimal("67510"), size=Decimal("0.5"), side=Side.ASK)

        book = L4BookSnapshot(
            coin="BTC",
            bids={Decimal("67500"): (bid_order,)},
            asks={Decimal("67510"): (ask_order,)},
            timestamp_ms=1700000000000,
        )

        assert book.best_bid == Decimal("67500")
        assert book.best_ask == Decimal("67510")
        assert book.mid_price == Decimal("67505")
        assert book.total_bid_size == Decimal("1.0")
        assert book.total_ask_size == Decimal("0.5")

    def test_empty_book(self):
        book = L4BookSnapshot(coin="BTC", bids={}, asks={}, timestamp_ms=0)
        assert book.best_bid is None
        assert book.best_ask is None
        assert book.mid_price is None
        assert book.total_bid_size == Decimal("0")

    def test_multiple_orders_at_price(self):
        o1 = L4Order(oid=1, user="0xa", price=Decimal("67500"), size=Decimal("1.0"), side=Side.BID)
        o2 = L4Order(oid=2, user="0xb", price=Decimal("67500"), size=Decimal("2.0"), side=Side.BID)
        o3 = L4Order(oid=3, user="0xc", price=Decimal("67490"), size=Decimal("0.5"), side=Side.BID)

        book = L4BookSnapshot(
            coin="BTC",
            bids={Decimal("67500"): (o1, o2), Decimal("67490"): (o3,)},
            asks={},
            timestamp_ms=1700000000000,
        )

        assert book.best_bid == Decimal("67500")
        assert book.total_bid_size == Decimal("3.5")
