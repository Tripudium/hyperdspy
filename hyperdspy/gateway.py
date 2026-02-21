import logging
from typing import Protocol

from eth_account import Account
from eth_account.signers.local import LocalAccount
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info
from hyperliquid.utils.types import Cloid

from hyperdspy.config import Config

logger = logging.getLogger(__name__)


class ExecutionBackend(Protocol):
    """Protocol that both LiveExecution and PaperExecution implement."""

    def place_order(
        self,
        coin: str,
        is_buy: bool,
        sz: float,
        limit_px: float,
        order_type: dict,
        reduce_only: bool = False,
        cloid: str | None = None,
    ) -> dict: ...

    def place_bulk_orders(self, orders: list[dict]) -> dict: ...

    def cancel_order(self, coin: str, oid: int) -> dict: ...

    def cancel_bulk(self, cancels: list[dict]) -> dict: ...

    def cancel_all(self, coin: str) -> dict: ...

    def get_open_orders(self) -> list[dict]: ...

    def get_user_state(self) -> dict: ...

    def get_user_fills(self) -> list[dict]: ...


class LiveExecution:
    """Production execution backend wrapping the SDK Exchange."""

    def __init__(self, config: Config, info: Info):
        self._config = config
        self._info = info
        wallet: LocalAccount = Account.from_key(config.wallet.secret_key)
        self._exchange = Exchange(
            wallet=wallet,
            base_url=config.base_url,
            vault_address=config.wallet.vault_address,
            account_address=config.wallet.account_address,
        )
        self._address = config.wallet.account_address

    def place_order(self, coin, is_buy, sz, limit_px, order_type, reduce_only=False, cloid=None):
        cl = Cloid.from_str(cloid) if cloid else None
        return self._exchange.order(coin, is_buy, sz, limit_px, order_type, reduce_only, cl)

    def place_bulk_orders(self, orders):
        return self._exchange.bulk_orders(orders)

    def cancel_order(self, coin, oid):
        return self._exchange.cancel(coin, oid)

    def cancel_bulk(self, cancels):
        return self._exchange.bulk_cancel(cancels)

    def cancel_all(self, coin):
        open_orders = self._info.open_orders(self._address)
        coin_orders = [o for o in open_orders if o["coin"] == coin]
        if not coin_orders:
            return {"status": "ok", "cancelled": 0}
        cancels = [{"coin": o["coin"], "oid": o["oid"]} for o in coin_orders]
        return self._exchange.bulk_cancel(cancels)

    def get_open_orders(self):
        return self._info.open_orders(self._address)

    def get_user_state(self):
        return self._info.user_state(self._address)

    def get_user_fills(self):
        return self._info.user_fills(self._address)


class Gateway:
    """Unified interface for market data and execution.

    Owns the SDK Info instance (with WebSocket) and delegates execution
    to either LiveExecution or PaperExecution depending on config.
    """

    def __init__(self, config: Config, info: Info, execution: ExecutionBackend):
        self.config = config
        self.info = info
        self.execution = execution

    @classmethod
    def create(cls, config: Config) -> "Gateway":
        """Factory: build the right execution backend based on config."""
        info = Info(config.base_url, skip_ws=False)

        if config.paper_mode:
            from hyperdspy.paper import PaperExecution

            execution = PaperExecution(config, info)
        else:
            execution = LiveExecution(config, info)

        return cls(config, info, execution)

    def subscribe_l2(self, coin: str, callback) -> int:
        return self.info.subscribe({"type": "l2Book", "coin": coin}, callback)

    def subscribe_trades(self, coin: str, callback) -> int:
        return self.info.subscribe({"type": "trades", "coin": coin}, callback)

    def subscribe_user_fills(self, user: str, callback) -> int:
        return self.info.subscribe({"type": "userFills", "user": user}, callback)

    def subscribe_order_updates(self, user: str, callback) -> int:
        return self.info.subscribe({"type": "orderUpdates", "user": user}, callback)

    def subscribe_bbo(self, coin: str, callback) -> int:
        return self.info.subscribe({"type": "bbo", "coin": coin}, callback)

    def get_l2_snapshot(self, coin: str) -> dict:
        return self.info.l2_snapshot(coin)

    def get_all_mids(self) -> dict:
        return self.info.all_mids()

    def get_meta(self) -> dict:
        return self.info.meta()

    def shutdown(self):
        """Stop the WebSocket manager."""
        if hasattr(self.info, "ws_manager") and self.info.ws_manager is not None:
            self.info.ws_manager.stop()
