# Architecture Overview

## System Design

HyperDSPY is organized around a central `Engine` that wires together market data feeds, a strategy, and an execution backend. The system uses two threads: a WebSocket background thread (managed by the SDK) and a main thread running the strategy tick loop.

```
                        WebSocket Thread                     Main Thread
                        ================                     ===========

Hyperliquid API  ────>  SDK WebsocketManager
                             │
                             ├── on_l2_update()  ────────>  OrderBook.update()
                             │                              (lock, swap snapshot)
                             │
                             ├── on_user_fills()  ───────>  OrderManager.on_fill()
                             │                              Strategy.on_fill()
                             │
                             └── on_order_updates()  ────>  OrderManager.on_order_update()


order_book_server  ──>  L4Client (separate WS)
                             │
                             ├── callback  ──────────────>  DataRecorder.record_l4()
                             └── internal state  ────────>  L4BookSnapshot


                              Engine tick loop (every N seconds):
                              ===================================
                              1. OrderBook.get(coin)       ← read snapshot (lock)
                              2. get_user_state()          ← REST call
                              3. OrderManager.get_open()   ← read orders (lock)
                              4. Strategy.on_tick(book, account, orders)
                                       │
                                       ▼
                                  StrategyDecision
                                       │
                                       ▼
                              5. cancel_all() + place_bulk()
```

## Component Responsibilities

### Engine (`engine.py`)

The orchestrator. Creates all other components, subscribes to WebSocket feeds, runs the tick loop, and handles graceful shutdown on SIGINT/SIGTERM. The tick loop:

1. Polls the latest order book snapshot (lock-free read of an immutable object)
2. Fetches account state via REST
3. Calls `strategy.on_tick()` for each configured coin
4. Executes the returned `StrategyDecision` (cancel stale orders, place new ones)

### Gateway (`gateway.py`)

Thin facade over the SDK's `Info` and `Exchange` classes. Provides a unified interface and owns the single WebSocket connection. The `ExecutionBackend` protocol enables swapping between live and paper execution.

### OrderBook (`orderbook.py`)

Thread-safe container for L2 book snapshots. Uses a lock + immutable snapshot swap pattern:

- **Writer** (WS thread): Parses raw SDK data into a frozen `BookSnapshot`, swaps the dict reference under lock
- **Reader** (main thread): Reads the reference under lock, then uses the immutable object freely

Since `BookSnapshot` is a frozen dataclass with tuple fields, there is zero risk of concurrent mutation after reading.

### OrderManager (`order_manager.py`)

Tracks every order the system places. Each order gets a client order ID (cloid) at creation. A reverse index (`oid -> cloid`) allows reconciliation when fills arrive from WebSocket keyed by exchange-assigned oid.

### Strategy (`strategy.py`)

Abstract base class. Strategies return **desired state** ("I want these orders on the book"), not imperative commands. The engine handles the reconciliation -- cancelling stale orders and placing new ones. This prevents bugs from strategies that forget to clean up.

### Paper Trading (`paper.py`)

Implements the same `ExecutionBackend` protocol as `LiveExecution` but simulates order matching locally. Resting limit orders are checked against the live order book each tick. The SDK response format is mirrored exactly so the `OrderManager` works identically for both modes.

### L4 Client (`l4_client.py`)

A standalone WebSocket client (separate from the SDK's WS) that connects to a Hyperliquid `order_book_server`. Handles the snapshot-then-diffs protocol and maintains an in-memory `L4BookSnapshot` per coin.

### Data Recorder (`recorder.py`)

Pluggable writer system that records L2 snapshots, L4 messages, and trades to disk. Supports JSON lines and CSV formats with automatic daily file rotation.

## Threading Model

| Shared Resource | Writer Thread | Reader Thread | Protection |
|---|---|---|---|
| `OrderBook._books` | WebSocket | Main (tick loop) | `threading.Lock` |
| `OrderManager._orders` | WebSocket + Main | Main | `threading.Lock` |
| `L4Client._books` | L4 WS | Main | `threading.Lock` |

All snapshot types (`BookSnapshot`, `L4BookSnapshot`, `Fill`) are frozen dataclasses. Once a reference is read under the lock, the object is safe to use without further synchronization.

## Why Not Async?

The SDK's WebSocket is thread-based (`websocket-client` library), not async. Introducing `asyncio` would require a thread-async bridge that adds complexity without benefit. The tick loop runs at human-scale intervals (100ms-10s), so threads + locks are the right fit.
