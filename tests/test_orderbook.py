import threading
from decimal import Decimal

from hyperdspy.orderbook import OrderBook


class TestOrderBook:
    def test_update_and_get(self, sample_sdk_l2_data):
        ob = OrderBook()
        assert ob.get("BTC") is None

        ob.update(sample_sdk_l2_data)
        book = ob.get("BTC")

        assert book is not None
        assert book.coin == "BTC"
        assert book.mid_price == Decimal("67505.0")

    def test_get_all(self, sample_sdk_l2_data):
        ob = OrderBook()
        ob.update(sample_sdk_l2_data)

        eth_data = {
            "coin": "ETH",
            "time": 1700000000000,
            "levels": [
                [{"px": "3000.0", "sz": "10.0", "n": 5}],
                [{"px": "3001.0", "sz": "8.0", "n": 3}],
            ],
        }
        ob.update(eth_data)

        all_books = ob.get_all()
        assert len(all_books) == 2
        assert "BTC" in all_books
        assert "ETH" in all_books

    def test_update_replaces_snapshot(self, sample_sdk_l2_data):
        ob = OrderBook()
        ob.update(sample_sdk_l2_data)

        updated_data = {
            "coin": "BTC",
            "time": 1700000001000,
            "levels": [
                [{"px": "68000.0", "sz": "1.0", "n": 1}],
                [{"px": "68010.0", "sz": "1.0", "n": 1}],
            ],
        }
        ob.update(updated_data)

        book = ob.get("BTC")
        assert book.mid_price == Decimal("68005.0")
        assert book.timestamp_ms == 1700000001000

    def test_thread_safety(self, sample_sdk_l2_data):
        """Verify concurrent reads and writes don't crash."""
        ob = OrderBook()
        errors = []

        def writer():
            try:
                for i in range(100):
                    data = dict(sample_sdk_l2_data)
                    data["time"] = 1700000000000 + i
                    ob.update(data)
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(100):
                    book = ob.get("BTC")
                    if book:
                        _ = book.mid_price
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer), threading.Thread(target=reader)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
