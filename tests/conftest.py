import pytest

from hyperdspy.config import Config, TradingConfig, WalletConfig
from hyperdspy.models import BookSnapshot


@pytest.fixture
def sample_config():
    return Config(
        wallet=WalletConfig(secret_key="0x" + "ab" * 32, account_address="0x" + "cd" * 20),
        trading=TradingConfig(coins=["BTC", "ETH"]),
        paper_mode=True,
    )


@pytest.fixture
def sample_sdk_l2_data():
    """Raw SDK L2BookData as received from WebSocket or REST."""
    return {
        "coin": "BTC",
        "time": 1700000000000,
        "levels": [
            [
                {"px": "67500.0", "sz": "1.5", "n": 3},
                {"px": "67490.0", "sz": "2.0", "n": 5},
                {"px": "67480.0", "sz": "0.8", "n": 2},
            ],
            [
                {"px": "67510.0", "sz": "1.2", "n": 4},
                {"px": "67520.0", "sz": "3.0", "n": 6},
                {"px": "67530.0", "sz": "0.5", "n": 1},
            ],
        ],
    }


@pytest.fixture
def sample_book(sample_sdk_l2_data):
    return BookSnapshot.from_sdk(sample_sdk_l2_data)


@pytest.fixture
def sample_sdk_fill():
    """Raw SDK fill dict as received from WebSocket."""
    return {
        "coin": "BTC",
        "side": "B",
        "px": "67500.0",
        "sz": "0.001",
        "oid": 12345,
        "fee": "0.01",
        "time": 1700000001000,
        "closedPnl": "0",
        "crossed": False,
    }
