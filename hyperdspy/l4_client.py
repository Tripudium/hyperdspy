"""WebSocket client for Hyperliquid order_book_server L4 feed.

Connects to a separate order_book_server instance (not the public API).
L4 data provides individual order-level data with wallet addresses.

The server sends a full snapshot on subscription, followed by block-batched diffs.

Requires: a running order_book_server (https://github.com/hyperliquid-dex/order_book_server)
or a hosted provider (e.g., Dwellir).
"""

import json
import logging
import threading
import time
from collections import defaultdict
from decimal import Decimal
from typing import Callable, Optional

import websocket

from hyperdspy.models import L4BookSnapshot, L4Order, Side

logger = logging.getLogger(__name__)


class L4Client(threading.Thread):
    """WebSocket client that streams L4 order book data.

    Runs as a daemon thread. Maintains in-memory L4BookSnapshot per coin.
    Calls registered callbacks on each update.
    """

    def __init__(self, server_url: str, reconnect_delay: float = 5.0):
        super().__init__(daemon=True)
        self._server_url = server_url
        self._reconnect_delay = reconnect_delay
        self._stop_event = threading.Event()
        self._ws: Optional[websocket.WebSocketApp] = None
        self._ws_ready = False
        self._queued_subscriptions: list[str] = []

        # State
        self._lock = threading.Lock()
        self._books: dict[str, L4BookSnapshot] = {}
        self._raw_books: dict[str, dict] = {}  # coin -> {side: {price: [orders]}}
        self._callbacks: dict[str, list[Callable]] = defaultdict(list)  # coin -> callbacks
        self._snapshot_received: set[str] = set()

        # Ping thread
        self._ping_thread: Optional[threading.Thread] = None

    def run(self):
        """Main thread loop with reconnection."""
        while not self._stop_event.is_set():
            try:
                self._connect()
            except Exception:
                logger.exception("L4 WebSocket error")

            if not self._stop_event.is_set():
                logger.info(f"L4 reconnecting in {self._reconnect_delay}s...")
                self._stop_event.wait(self._reconnect_delay)

    def _connect(self):
        self._ws_ready = False
        self._snapshot_received.clear()
        self._ws = websocket.WebSocketApp(
            self._server_url,
            on_message=self._on_message,
            on_open=self._on_open,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        self._ping_thread = threading.Thread(target=self._send_pings, daemon=True)
        self._ping_thread.start()
        self._ws.run_forever()

    def _send_pings(self):
        while not self._stop_event.wait(30):
            if self._ws and self._ws_ready:
                try:
                    self._ws.send(json.dumps({"method": "ping"}))
                except Exception:
                    break

    def stop(self):
        """Stop the client and close the WebSocket."""
        self._stop_event.set()
        if self._ws:
            self._ws.close()

    def subscribe(self, coin: str, callback: Optional[Callable] = None) -> None:
        """Subscribe to L4 book updates for a coin.

        Args:
            coin: e.g. "BTC", "ETH"
            callback: Called with (coin, raw_msg_dict) on each update.
                      The raw_msg is either a snapshot or diff message.
        """
        if callback:
            self._callbacks[coin].append(callback)

        if self._ws_ready:
            self._send_subscribe(coin)
        else:
            self._queued_subscriptions.append(coin)

    def _send_subscribe(self, coin: str):
        msg = json.dumps({"method": "subscribe", "subscription": {"type": "l4Book", "coin": coin}})
        try:
            self._ws.send(msg)
            logger.info(f"L4 subscribed to {coin}")
        except Exception:
            logger.exception(f"Failed to subscribe L4 for {coin}")

    def get(self, coin: str) -> Optional[L4BookSnapshot]:
        """Get the latest L4 book snapshot. Thread-safe."""
        with self._lock:
            return self._books.get(coin)

    # --- WebSocket handlers ---

    def _on_open(self, _ws):
        logger.info(f"L4 WebSocket connected to {self._server_url}")
        self._ws_ready = True
        for coin in self._queued_subscriptions:
            self._send_subscribe(coin)
        self._queued_subscriptions.clear()

    def _on_message(self, _ws, message: str):
        if message == "Websocket connection established.":
            return

        try:
            msg = json.loads(message)
        except json.JSONDecodeError:
            logger.warning(f"L4 invalid JSON: {message[:200]}")
            return

        channel = msg.get("channel")
        if channel == "pong":
            return

        if channel == "l4Book":
            self._handle_l4_message(msg)

    def _on_error(self, _ws, error):
        logger.error(f"L4 WebSocket error: {error}")

    def _on_close(self, _ws, close_status_code, close_msg):
        logger.info(f"L4 WebSocket closed: {close_status_code} {close_msg}")
        self._ws_ready = False

    # --- L4 data processing ---

    def _handle_l4_message(self, msg: dict):
        data = msg.get("data", {})
        coin = data.get("coin", "")

        if not coin:
            return

        # Notify raw callbacks (for recorder)
        for cb in self._callbacks.get(coin, []):
            try:
                cb(coin, data)
            except Exception:
                logger.exception("Error in L4 callback")

        # Update internal book state
        if coin not in self._snapshot_received:
            self._apply_snapshot(coin, data)
            self._snapshot_received.add(coin)
        else:
            self._apply_diff(coin, data)

    def _apply_snapshot(self, coin: str, data: dict):
        """Process the initial full L4 snapshot."""
        bids: dict[Decimal, list[L4Order]] = {}
        asks: dict[Decimal, list[L4Order]] = {}

        for order_raw in data.get("bids", []):
            order = L4Order.from_raw(order_raw, Side.BID)
            bids.setdefault(order.price, []).append(order)

        for order_raw in data.get("asks", []):
            order = L4Order.from_raw(order_raw, Side.ASK)
            asks.setdefault(order.price, []).append(order)

        snapshot = L4BookSnapshot(
            coin=coin,
            bids={px: tuple(orders) for px, orders in bids.items()},
            asks={px: tuple(orders) for px, orders in asks.items()},
            timestamp_ms=data.get("time", int(time.time() * 1000)),
        )

        with self._lock:
            self._books[coin] = snapshot
            # Store mutable copy for diff application
            self._raw_books[coin] = {
                "bids": {px: list(orders) for px, orders in bids.items()},
                "asks": {px: list(orders) for px, orders in asks.items()},
            }

        logger.info(
            f"L4 snapshot {coin}: "
            f"{sum(len(v) for v in bids.values())} bids, "
            f"{sum(len(v) for v in asks.values())} asks"
        )

    def _apply_diff(self, coin: str, data: dict):
        """Apply an incremental L4 diff to the current book state."""
        with self._lock:
            raw = self._raw_books.get(coin)
            if raw is None:
                return

            # Process bid diffs
            for diff in data.get("bidDiffs", []):
                self._apply_side_diff(raw["bids"], diff, Side.BID)

            # Process ask diffs
            for diff in data.get("askDiffs", []):
                self._apply_side_diff(raw["asks"], diff, Side.ASK)

            # Rebuild frozen snapshot
            self._books[coin] = L4BookSnapshot(
                coin=coin,
                bids={px: tuple(orders) for px, orders in raw["bids"].items() if orders},
                asks={px: tuple(orders) for px, orders in raw["asks"].items() if orders},
                timestamp_ms=data.get("time", int(time.time() * 1000)),
            )

    def _apply_side_diff(self, side_book: dict[Decimal, list[L4Order]], diff: dict, side: Side):
        """Apply a single diff entry to one side of the book.

        Diff format (inferred from order_book_server):
        - Add: {"oid": int, "user": str, "limitPx": str, "sz": str}
        - Remove: {"oid": int, "sz": "0"} or absent from update
        - Modify: {"oid": int, "user": str, "limitPx": str, "sz": str}
        """
        oid = diff.get("oid")
        px = Decimal(diff["limitPx"])
        new_sz = Decimal(diff.get("sz", "0"))

        if new_sz == 0:
            # Remove order
            if px in side_book:
                side_book[px] = [o for o in side_book[px] if o.oid != oid]
                if not side_book[px]:
                    del side_book[px]
        else:
            order = L4Order.from_raw(diff, side)
            if px in side_book:
                # Replace if exists, else append
                existing = [o for o in side_book[px] if o.oid != oid]
                existing.append(order)
                side_book[px] = existing
            else:
                side_book[px] = [order]
