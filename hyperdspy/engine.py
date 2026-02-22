import logging
import signal
import threading
import time
from decimal import Decimal

from hyperdspy.config import Config
from hyperdspy.gateway import Gateway
from hyperdspy.models import AccountState, Fill, Position
from hyperdspy.order_manager import OrderManager
from hyperdspy.orderbook import OrderBook
from hyperdspy.strategy import Strategy

logger = logging.getLogger(__name__)


class Engine:
    """Main event loop connecting market data, strategy, and execution.

    Lifecycle:
    1. __init__: Create components (gateway, order book, order manager)
    2. run(strategy): Subscribe to feeds, enter tick loop
    3. tick loop: Poll book -> call strategy.on_tick() -> reconcile orders
    4. shutdown: Cancel all orders, disconnect WebSocket
    """

    def __init__(self, config: Config, strategy: Strategy | None = None):
        self.config = config
        self.strategy = strategy
        self.gateway = Gateway.create(config)
        self.orderbook = OrderBook()
        self.order_manager = OrderManager(self.gateway.execution)
        self._running = threading.Event()
        self._setup_logging()

        # Optional components
        self.l4_client = None
        self.recorder = None

        if config.l4_server_url:
            from hyperdspy.l4_client import L4Client

            self.l4_client = L4Client(config.l4_server_url)

        if config.recording.enabled:
            from hyperdspy.recorder import DataRecorder

            self.recorder = DataRecorder(config.recording)

    def _setup_logging(self):
        logging.basicConfig(
            level=getattr(logging, self.config.log_level.upper(), logging.INFO),
            format="%(asctime)s.%(msecs)03d [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
        logging.getLogger("websocket").setLevel(logging.WARNING)
        logging.getLogger("urllib3").setLevel(logging.WARNING)

    def run(self, strategy: Strategy | None = None):
        """Start the engine. Blocks until interrupted (Ctrl-C) or stop() is called."""
        if strategy:
            self.strategy = strategy
        if self.strategy is None:
            raise ValueError("No strategy provided. Pass one to Engine() or run().")

        self._running.set()
        self._setup_signal_handlers()

        coins = self.config.trading.coins
        mode = "PAPER" if self.config.paper_mode else "LIVE"
        logger.info(f"Starting engine: coins={coins}, mode={mode}")

        # Subscribe to L2 book for each coin
        for coin in coins:
            self._subscribe_book(coin)

        # Subscribe to trades (for recording)
        if self.recorder and self.config.recording.record_trades:
            for coin in coins:
                self._subscribe_trades(coin)

        # Start L4 client if configured
        if self.l4_client:
            self.l4_client.start()
            for coin in coins:
                self.l4_client.subscribe(coin, self._on_l4_update)
            logger.info(f"L4 client started: {self.config.l4_server_url}")

        # Subscribe to user events (live mode only)
        if not self.config.paper_mode:
            address = self.config.wallet.account_address
            self.gateway.subscribe_user_fills(address, self._on_user_fills)
            self.gateway.subscribe_order_updates(address, self._on_order_updates)

        self.strategy.on_start(coins)
        logger.info("Engine started. Entering tick loop.")

        try:
            self._tick_loop()
        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt received.")
        finally:
            self.shutdown()

    def stop(self):
        """Signal the engine to stop."""
        self._running.clear()

    def shutdown(self):
        """Clean shutdown: cancel all orders, disconnect, close recorder."""
        logger.info("Shutting down engine...")
        if self.strategy:
            self.strategy.on_stop()

        for coin in self.config.trading.coins:
            try:
                self.order_manager.cancel_all(coin)
            except Exception:
                logger.exception(f"Error cancelling orders for {coin}")

        if self.l4_client:
            try:
                self.l4_client.stop()
            except Exception:
                logger.exception("Error stopping L4 client")

        if self.recorder:
            try:
                self.recorder.close()
                logger.info("Data recorder closed.")
            except Exception:
                logger.exception("Error closing recorder")

        try:
            self.gateway.shutdown()
        except Exception:
            logger.exception("Error disconnecting WebSocket")

        logger.info("Engine stopped.")

    def _tick_loop(self):
        interval = self.config.tick_interval_s
        while self._running.is_set():
            tick_start = time.monotonic()
            try:
                self._tick()
            except Exception:
                logger.exception("Error in tick")

            elapsed = time.monotonic() - tick_start
            sleep_time = max(0, interval - elapsed)
            if sleep_time > 0:
                self._running.wait(sleep_time)

    def _tick(self):
        """Single tick: gather state, call strategy, execute decisions."""
        # In paper mode, check resting orders against current book
        if self.config.paper_mode:
            from hyperdspy.paper import PaperExecution

            if isinstance(self.gateway.execution, PaperExecution):
                books = self.orderbook.get_all()
                new_fills = self.gateway.execution.check_resting_orders(books)
                for fill_data in new_fills:
                    fill = Fill.from_sdk(fill_data)
                    self.order_manager.on_fill(fill)
                    self.strategy.on_fill(fill)

        account = self._get_account_state()

        for coin in self.config.trading.coins:
            book = self.orderbook.get(coin)
            open_orders = self.order_manager.get_open_orders(coin)
            decision = self.strategy.on_tick(coin, book, account, open_orders)

            if decision is not None:
                self._execute_decision(decision)

        self.order_manager.cleanup_terminal()

    def _execute_decision(self, decision):
        """Turn a StrategyDecision into actual orders."""
        if decision.cancel_all_first:
            self.order_manager.cancel_all(decision.coin)

        if decision.desired_orders:
            self.order_manager.place_bulk(decision.coin, decision.desired_orders)

    def _get_account_state(self) -> AccountState:
        """Fetch current account state from the exchange."""
        try:
            raw = self.gateway.execution.get_user_state()
            margin = raw.get("marginSummary", raw.get("crossMarginSummary", {}))
            positions = {}
            for ap in raw.get("assetPositions", []):
                pos = ap["position"]
                coin = pos["coin"]
                positions[coin] = Position(
                    coin=coin,
                    size=Decimal(pos.get("szi", "0")),
                    entry_price=Decimal(pos.get("entryPx", "0") or "0"),
                    unrealized_pnl=Decimal(pos.get("unrealizedPnl", "0")),
                    leverage=pos.get("leverage", {}).get("value", 1),
                    liquidation_price=Decimal(pos["liquidationPx"]) if pos.get("liquidationPx") else None,
                    margin_used=Decimal(pos.get("marginUsed", "0")),
                )
            return AccountState(
                account_value=Decimal(margin.get("accountValue", "0")),
                total_margin_used=Decimal(margin.get("totalMarginUsed", "0")),
                withdrawable=Decimal(raw.get("withdrawable", "0")),
                positions=positions,
            )
        except Exception:
            logger.exception("Failed to get account state")
            return AccountState(
                account_value=Decimal("0"),
                total_margin_used=Decimal("0"),
                withdrawable=Decimal("0"),
                positions={},
            )

    # --- WebSocket callbacks (called from WS background thread) ---

    def _subscribe_book(self, coin: str):
        """Subscribe to L2 book updates. Seeds with REST snapshot first."""
        try:
            snapshot = self.gateway.get_l2_snapshot(coin)
            self.orderbook.update(snapshot)
            book = self.orderbook.get(coin)
            logger.info(f"Seeded {coin} book: mid={book.mid_price if book else 'N/A'}")
        except Exception:
            logger.exception(f"Failed to seed {coin} book")

        def on_l2_update(msg):
            try:
                self.orderbook.update(msg["data"])
                if self.recorder:
                    book = self.orderbook.get(coin)
                    if book:
                        self.recorder.record_l2(coin, book)
            except Exception:
                logger.exception("Error processing L2 update")

        self.gateway.subscribe_l2(coin, on_l2_update)

    def _subscribe_trades(self, coin: str):
        """Subscribe to trade events for recording."""

        def on_trade(msg):
            try:
                trades = msg.get("data", [])
                if self.recorder:
                    for trade in trades:
                        self.recorder.record_trade(coin, trade)
            except Exception:
                logger.exception("Error processing trade")

        self.gateway.subscribe_trades(coin, on_trade)

    def _on_l4_update(self, coin: str, raw_msg: dict):
        """L4 client callback -- records raw L4 data."""
        if self.recorder:
            try:
                self.recorder.record_l4(coin, raw_msg)
            except Exception:
                logger.exception("Error recording L4 data")

    def _on_user_fills(self, msg):
        try:
            fills_data = msg.get("data", {}).get("fills", [])
            for fill_data in fills_data:
                fill = Fill.from_sdk(fill_data)
                self.order_manager.on_fill(fill)
                self.strategy.on_fill(fill)
        except Exception:
            logger.exception("Error processing user fill")

    def _on_order_updates(self, msg):
        try:
            self.order_manager.on_order_update(msg.get("data", []))
        except Exception:
            logger.exception("Error processing order update")

    def _setup_signal_handlers(self):
        def handler(signum, frame):
            logger.info(f"Signal {signum} received, stopping...")
            self.stop()

        signal.signal(signal.SIGINT, handler)
        signal.signal(signal.SIGTERM, handler)
