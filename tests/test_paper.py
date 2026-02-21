from decimal import Decimal

from hyperdspy.config import Config, TradingConfig, WalletConfig
from hyperdspy.models import BookSnapshot, PriceLevel
from hyperdspy.paper import PaperExecution


def make_config():
    return Config(
        wallet=WalletConfig(secret_key="0x" + "ab" * 32, account_address="0x" + "cd" * 20),
        trading=TradingConfig(coins=["BTC"]),
        paper_mode=True,
    )


def make_book(bid_px="67500.0", ask_px="67510.0"):
    return BookSnapshot(
        coin="BTC",
        bids=(PriceLevel(price=Decimal(bid_px), size=Decimal("1.0"), num_orders=1),),
        asks=(PriceLevel(price=Decimal(ask_px), size=Decimal("1.0"), num_orders=1),),
        timestamp_ms=1700000000000,
    )


class TestPaperExecution:
    def test_place_and_get_orders(self):
        paper = PaperExecution(make_config(), info=None)
        result = paper.place_order("BTC", True, 0.1, 67500.0, {"limit": {"tif": "Gtc"}})

        assert result["status"] == "ok"
        assert "resting" in result["response"]["data"]["statuses"][0]

        orders = paper.get_open_orders()
        assert len(orders) == 1
        assert orders[0]["coin"] == "BTC"

    def test_cancel_order(self):
        paper = PaperExecution(make_config(), info=None)
        result = paper.place_order("BTC", True, 0.1, 67500.0, {"limit": {"tif": "Gtc"}})
        oid = result["response"]["data"]["statuses"][0]["resting"]["oid"]

        paper.cancel_order("BTC", oid)
        assert len(paper.get_open_orders()) == 0

    def test_cancel_all(self):
        paper = PaperExecution(make_config(), info=None)
        paper.place_order("BTC", True, 0.1, 67500.0, {"limit": {"tif": "Gtc"}})
        paper.place_order("BTC", False, 0.1, 67510.0, {"limit": {"tif": "Gtc"}})

        result = paper.cancel_all("BTC")
        assert result["cancelled"] == 2
        assert len(paper.get_open_orders()) == 0

    def test_check_resting_buy_fills(self):
        paper = PaperExecution(make_config(), info=None)
        paper.place_order("BTC", True, 0.1, 67510.0, {"limit": {"tif": "Gtc"}})  # bid at ask level

        books = {"BTC": make_book()}
        fills = paper.check_resting_orders(books)

        assert len(fills) == 1
        assert fills[0]["side"] == "B"
        assert len(paper.get_open_orders()) == 0

    def test_check_resting_sell_fills(self):
        paper = PaperExecution(make_config(), info=None)
        paper.place_order("BTC", False, 0.1, 67500.0, {"limit": {"tif": "Gtc"}})  # ask at bid level

        books = {"BTC": make_book()}
        fills = paper.check_resting_orders(books)

        assert len(fills) == 1
        assert fills[0]["side"] == "A"

    def test_no_fill_when_not_crossed(self):
        paper = PaperExecution(make_config(), info=None)
        paper.place_order("BTC", True, 0.1, 67400.0, {"limit": {"tif": "Gtc"}})  # bid well below ask

        books = {"BTC": make_book()}
        fills = paper.check_resting_orders(books)

        assert len(fills) == 0
        assert len(paper.get_open_orders()) == 1

    def test_position_tracking(self):
        paper = PaperExecution(make_config(), info=None, starting_balance=Decimal("10000"))
        paper.place_order("BTC", True, 0.1, 67510.0, {"limit": {"tif": "Gtc"}})

        books = {"BTC": make_book()}
        paper.check_resting_orders(books)

        state = paper.get_user_state()
        assert len(state["assetPositions"]) == 1
        pos = state["assetPositions"][0]["position"]
        assert Decimal(pos["szi"]) == Decimal("0.1")

    def test_bulk_orders(self):
        paper = PaperExecution(make_config(), info=None)
        orders = [
            {
                "coin": "BTC",
                "is_buy": True,
                "sz": 0.1,
                "limit_px": 67500.0,
                "order_type": {"limit": {"tif": "Gtc"}},
            },
            {
                "coin": "BTC",
                "is_buy": False,
                "sz": 0.1,
                "limit_px": 67510.0,
                "order_type": {"limit": {"tif": "Gtc"}},
            },
        ]
        result = paper.place_bulk_orders(orders)
        statuses = result["response"]["data"]["statuses"]
        assert len(statuses) == 2
        assert all("resting" in s for s in statuses)

    def test_user_state_default(self):
        paper = PaperExecution(make_config(), info=None, starting_balance=Decimal("50000"))
        state = paper.get_user_state()
        assert state["marginSummary"]["accountValue"] == "50000"
        assert state["assetPositions"] == []
