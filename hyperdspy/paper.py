import logging
import threading
import time
from decimal import Decimal

from hyperliquid.info import Info

from hyperdspy.config import Config
from hyperdspy.models import BookSnapshot

logger = logging.getLogger(__name__)


class PaperExecution:
    """Simulated execution backend for paper trading.

    Resting limit orders are checked against the live order book each tick.
    Tracks simulated positions and PnL with a starting paper balance.
    Response format mirrors the SDK so OrderManager works identically for both modes.
    """

    def __init__(self, config: Config, info: Info, starting_balance: Decimal = Decimal("10000")):
        self._config = config
        self._info = info
        self._address = config.wallet.account_address
        self._lock = threading.Lock()
        self._next_oid = 1
        self._open_orders: dict[int, dict] = {}
        self._fills: list[dict] = []
        self._positions: dict[str, dict] = {}
        self._balance_usd: Decimal = starting_balance

    def place_order(self, coin, is_buy, sz, limit_px, order_type, reduce_only=False, cloid=None):
        with self._lock:
            oid = self._next_oid
            self._next_oid += 1

        tif = order_type.get("limit", {}).get("tif", "Gtc")

        if tif == "Ioc":
            return self._try_immediate_fill(coin, is_buy, sz, limit_px, oid, cloid)

        order = {
            "coin": coin,
            "is_buy": is_buy,
            "sz": sz,
            "limit_px": limit_px,
            "order_type": order_type,
            "reduce_only": reduce_only,
            "cloid": cloid,
            "oid": oid,
            "time": int(time.time() * 1000),
        }
        with self._lock:
            self._open_orders[oid] = order

        return {
            "status": "ok",
            "response": {"type": "order", "data": {"statuses": [{"resting": {"oid": oid}}]}},
        }

    def place_bulk_orders(self, orders):
        statuses = []
        for req in orders:
            result = self.place_order(
                req["coin"],
                req["is_buy"],
                req["sz"],
                req["limit_px"],
                req["order_type"],
                req.get("reduce_only", False),
                str(req["cloid"]) if req.get("cloid") else None,
            )
            statuses.extend(result["response"]["data"]["statuses"])
        return {"status": "ok", "response": {"type": "order", "data": {"statuses": statuses}}}

    def cancel_order(self, coin, oid):
        with self._lock:
            self._open_orders.pop(oid, None)
        return {"status": "ok"}

    def cancel_bulk(self, cancels):
        with self._lock:
            for c in cancels:
                self._open_orders.pop(c["oid"], None)
        return {"status": "ok"}

    def cancel_all(self, coin):
        with self._lock:
            to_remove = [oid for oid, o in self._open_orders.items() if o["coin"] == coin]
            for oid in to_remove:
                del self._open_orders[oid]
        return {"status": "ok", "cancelled": len(to_remove)}

    def get_open_orders(self):
        with self._lock:
            return [
                {
                    "coin": o["coin"],
                    "oid": o["oid"],
                    "side": "B" if o["is_buy"] else "A",
                    "limitPx": str(o["limit_px"]),
                    "sz": str(o["sz"]),
                    "timestamp": o["time"],
                }
                for o in self._open_orders.values()
            ]

    def get_user_state(self):
        with self._lock:
            positions = []
            for pos in self._positions.values():
                positions.append({"type": "oneWay", "position": pos})
            return {
                "marginSummary": {
                    "accountValue": str(self._balance_usd),
                    "totalMarginUsed": "0",
                    "totalNtlPos": "0",
                    "totalRawUsd": str(self._balance_usd),
                },
                "crossMarginSummary": {
                    "accountValue": str(self._balance_usd),
                    "totalMarginUsed": "0",
                    "totalNtlPos": "0",
                    "totalRawUsd": str(self._balance_usd),
                },
                "withdrawable": str(self._balance_usd),
                "assetPositions": positions,
            }

    def get_user_fills(self):
        with self._lock:
            return list(self._fills)

    def check_resting_orders(self, books: dict[str, BookSnapshot]) -> list[dict]:
        """Called by engine each tick. Check resting orders against current book.

        Returns list of simulated fill dicts.
        """
        new_fills = []
        with self._lock:
            filled_oids = []
            for oid, order in self._open_orders.items():
                book = books.get(order["coin"])
                if book is None:
                    continue

                if order["is_buy"] and book.asks:
                    best_ask = float(book.asks[0].price)
                    if best_ask <= order["limit_px"]:
                        fill = self._simulate_fill(order, Decimal(str(best_ask)))
                        new_fills.append(fill)
                        filled_oids.append(oid)
                elif not order["is_buy"] and book.bids:
                    best_bid = float(book.bids[0].price)
                    if best_bid >= order["limit_px"]:
                        fill = self._simulate_fill(order, Decimal(str(best_bid)))
                        new_fills.append(fill)
                        filled_oids.append(oid)

            for oid in filled_oids:
                del self._open_orders[oid]

        return new_fills

    def _try_immediate_fill(self, coin, is_buy, sz, limit_px, oid, cloid):
        """Attempt to fill an IOC order against the current book snapshot."""
        try:
            snapshot = self._info.l2_snapshot(coin)
            levels = snapshot["levels"]
            if is_buy and levels[1]:
                best_ask = float(levels[1][0]["px"])
                if best_ask <= limit_px:
                    with self._lock:
                        self._simulate_fill(
                            {"coin": coin, "is_buy": is_buy, "sz": sz, "oid": oid, "cloid": cloid},
                            Decimal(str(best_ask)),
                        )
                    return {
                        "status": "ok",
                        "response": {"type": "order", "data": {"statuses": [{"filled": {"oid": oid}}]}},
                    }
            elif not is_buy and levels[0]:
                best_bid = float(levels[0][0]["px"])
                if best_bid >= limit_px:
                    with self._lock:
                        self._simulate_fill(
                            {"coin": coin, "is_buy": is_buy, "sz": sz, "oid": oid, "cloid": cloid},
                            Decimal(str(best_bid)),
                        )
                    return {
                        "status": "ok",
                        "response": {"type": "order", "data": {"statuses": [{"filled": {"oid": oid}}]}},
                    }
        except Exception:
            logger.exception("Paper IOC fill check failed")

        return {
            "status": "ok",
            "response": {"type": "order", "data": {"statuses": [{"error": "IOC would not fill"}]}},
        }

    def _simulate_fill(self, order: dict, fill_px: Decimal) -> dict:
        """Record a simulated fill and update position. Must be called under lock."""
        fill = {
            "coin": order["coin"],
            "oid": order["oid"],
            "side": "B" if order["is_buy"] else "A",
            "px": str(fill_px),
            "sz": str(order["sz"]),
            "time": int(time.time() * 1000),
            "closedPnl": "0",
            "crossed": True,
            "fee": "0",
        }
        self._fills.append(fill)
        self._update_position(order["coin"], order["is_buy"], Decimal(str(order["sz"])), fill_px)
        return fill

    def _update_position(self, coin: str, is_buy: bool, sz: Decimal, px: Decimal) -> None:
        """Update simulated position after a fill. Must be called under lock."""
        pos = self._positions.get(coin)
        if pos is None:
            szi = sz if is_buy else -sz
            self._positions[coin] = {
                "coin": coin,
                "szi": str(szi),
                "entryPx": str(px),
                "positionValue": str(abs(szi) * px),
                "unrealizedPnl": "0",
                "leverage": {"type": "cross", "value": 20},
                "liquidationPx": None,
                "marginUsed": str(abs(szi) * px / 20),
            }
        else:
            old_szi = Decimal(pos["szi"])
            delta = sz if is_buy else -sz
            new_szi = old_szi + delta
            if new_szi == 0:
                closed_pnl = (px - Decimal(pos["entryPx"])) * abs(delta) * (1 if old_szi > 0 else -1)
                self._balance_usd += closed_pnl
                del self._positions[coin]
            else:
                if (old_szi > 0 and delta > 0) or (old_szi < 0 and delta < 0):
                    old_entry = Decimal(pos["entryPx"])
                    new_entry = (old_entry * abs(old_szi) + px * abs(delta)) / abs(new_szi)
                    pos["entryPx"] = str(new_entry)
                pos["szi"] = str(new_szi)
                pos["positionValue"] = str(abs(new_szi) * px)
                pos["marginUsed"] = str(abs(new_szi) * px / 20)
