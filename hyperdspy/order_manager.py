import logging
import threading
import time
from decimal import Decimal
from typing import Optional

from hyperliquid.utils.types import Cloid

from hyperdspy.models import DesiredOrder, Fill, Order, OrderStatus, Side

logger = logging.getLogger(__name__)


class OrderManager:
    """Tracks all orders placed by the system.

    Thread safety: the order dict is accessed from the strategy/engine thread
    (place_order, cancel_order, get_open_orders) and the WebSocket callback thread
    (on_fill, on_order_update). A lock protects the shared _orders dict.
    """

    def __init__(self, execution_backend):
        self._execution = execution_backend
        self._lock = threading.Lock()
        self._orders: dict[str, Order] = {}  # cloid -> Order
        self._oid_to_cloid: dict[int, str] = {}  # reverse index
        self._cloid_counter = 0

    def _next_cloid(self) -> str:
        self._cloid_counter += 1
        return Cloid.from_int(self._cloid_counter).to_raw()

    def place_order(
        self,
        coin: str,
        side: Side,
        price: Decimal,
        size: Decimal,
        order_type: dict,
        reduce_only: bool = False,
    ) -> Order:
        """Place an order and track it internally. Called from the engine/strategy thread."""
        cloid = self._next_cloid()
        order = Order(
            coin=coin,
            side=side,
            price=price,
            size=size,
            order_type=order_type,
            reduce_only=reduce_only,
            cloid=cloid,
        )

        with self._lock:
            self._orders[cloid] = order

        try:
            result = self._execution.place_order(
                coin=coin,
                is_buy=order.is_buy,
                sz=float(size),
                limit_px=float(price),
                order_type=order_type,
                reduce_only=reduce_only,
                cloid=cloid,
            )
            self._process_order_response(cloid, result)
        except Exception:
            logger.exception(f"Failed to place order {cloid}")
            with self._lock:
                order.status = OrderStatus.REJECTED

        return order

    def place_bulk(self, coin: str, desired: list[DesiredOrder]) -> list[Order]:
        """Place multiple orders at once. Returns list of tracked Orders."""
        orders = []
        sdk_requests = []
        for d in desired:
            cloid = self._next_cloid()
            order = Order(
                coin=coin,
                side=d.side,
                price=d.price,
                size=d.size,
                order_type=d.order_type,
                reduce_only=d.reduce_only,
                cloid=cloid,
            )
            orders.append(order)
            sdk_requests.append(
                {
                    "coin": coin,
                    "is_buy": order.is_buy,
                    "sz": float(d.size),
                    "limit_px": float(d.price),
                    "order_type": d.order_type,
                    "reduce_only": d.reduce_only,
                    "cloid": Cloid.from_str(cloid),
                }
            )

        with self._lock:
            for o in orders:
                self._orders[o.cloid] = o

        try:
            result = self._execution.place_bulk_orders(sdk_requests)
            self._process_bulk_response(orders, result)
        except Exception:
            logger.exception("Failed to place bulk orders")
            with self._lock:
                for o in orders:
                    o.status = OrderStatus.REJECTED

        return orders

    def cancel_all(self, coin: str) -> None:
        """Cancel all open orders for a coin."""
        self._execution.cancel_all(coin)
        with self._lock:
            for order in self._orders.values():
                if order.coin == coin and not order.is_terminal:
                    order.status = OrderStatus.CANCELLED
                    order.updated_at_ms = int(time.time() * 1000)

    def get_open_orders(self, coin: Optional[str] = None) -> list[Order]:
        """Get all non-terminal orders, optionally filtered by coin."""
        with self._lock:
            result = [o for o in self._orders.values() if not o.is_terminal]
            if coin:
                result = [o for o in result if o.coin == coin]
            return result

    # --- WebSocket callbacks (called from WS thread) ---

    def on_fill(self, fill: Fill) -> None:
        """Process a fill event from the exchange."""
        with self._lock:
            cloid = self._oid_to_cloid.get(fill.oid)
            if cloid and cloid in self._orders:
                order = self._orders[cloid]
                order.filled_size += fill.size
                order.updated_at_ms = fill.timestamp_ms
                if order.filled_size >= order.size:
                    order.status = OrderStatus.FILLED
                else:
                    order.status = OrderStatus.PARTIALLY_FILLED

    def on_order_update(self, data: dict) -> None:
        """Process order status updates from the 'orderUpdates' WebSocket channel."""
        with self._lock:
            updates = data if isinstance(data, list) else [data]
            for update in updates:
                oid = update.get("oid")
                status_str = update.get("status", "")
                cloid = self._oid_to_cloid.get(oid)
                if cloid and cloid in self._orders:
                    order = self._orders[cloid]
                    if status_str == "canceled":
                        order.status = OrderStatus.CANCELLED
                    elif status_str == "filled":
                        order.status = OrderStatus.FILLED
                    elif status_str == "rejected":
                        order.status = OrderStatus.REJECTED
                    order.updated_at_ms = int(time.time() * 1000)

    def _process_order_response(self, cloid: str, result: dict) -> None:
        """Parse SDK response from a single order placement."""
        with self._lock:
            order = self._orders.get(cloid)
            if not order:
                return
            statuses = result.get("response", {}).get("data", {}).get("statuses", [])
            if statuses:
                status = statuses[0]
                if "resting" in status:
                    order.oid = status["resting"]["oid"]
                    order.status = OrderStatus.OPEN
                    self._oid_to_cloid[order.oid] = cloid
                elif "filled" in status:
                    order.oid = status["filled"]["oid"]
                    order.status = OrderStatus.FILLED
                    order.filled_size = order.size
                    self._oid_to_cloid[order.oid] = cloid
                elif "error" in status:
                    order.status = OrderStatus.REJECTED
                    logger.warning(f"Order {cloid} rejected: {status['error']}")

    def _process_bulk_response(self, orders: list[Order], result: dict) -> None:
        """Parse SDK response from a bulk order placement."""
        statuses = result.get("response", {}).get("data", {}).get("statuses", [])
        with self._lock:
            for order, status in zip(orders, statuses):
                if "resting" in status:
                    order.oid = status["resting"]["oid"]
                    order.status = OrderStatus.OPEN
                    self._oid_to_cloid[order.oid] = order.cloid
                elif "filled" in status:
                    order.oid = status["filled"]["oid"]
                    order.status = OrderStatus.FILLED
                    order.filled_size = order.size
                    self._oid_to_cloid[order.oid] = order.cloid
                elif "error" in status:
                    order.status = OrderStatus.REJECTED

    def cleanup_terminal(self, max_age_ms: int = 300_000) -> None:
        """Remove terminal orders older than max_age_ms from tracking."""
        cutoff = int(time.time() * 1000) - max_age_ms
        with self._lock:
            to_remove = [cloid for cloid, o in self._orders.items() if o.is_terminal and o.updated_at_ms < cutoff]
            for cloid in to_remove:
                order = self._orders.pop(cloid)
                if order.oid:
                    self._oid_to_cloid.pop(order.oid, None)
