# Use Case: Market Making on Hyperliquid

This walkthrough builds a market making strategy from scratch, tests it in paper mode, records data for analysis, and prepares for live deployment.

## 1. Setup

Install the project and create your config:

```bash
cd hyperdspy
uv sync
```

Create `config.json`:

```json
{
    "secret_key": "0xYOUR_PRIVATE_KEY",
    "account_address": "0xYOUR_WALLET_ADDRESS",
    "paper_mode": true,
    "coins": ["ETH"],
    "tick_interval_s": 2.0,
    "log_level": "INFO",
    "recording": {
        "enabled": true,
        "output_dir": "data",
        "format": "jsonl"
    }
}
```

## 2. Understand the Market Data

Before writing a strategy, explore the data in a Jupyter notebook:

```bash
uv run jupyter lab
```

```python
from hyperliquid.info import Info
from hyperliquid.utils.constants import MAINNET_API_URL

info = Info(MAINNET_API_URL, skip_ws=True)

# L2 order book snapshot
book = info.l2_snapshot("ETH")
print(f"Best bid: {book['levels'][0][0]}")
print(f"Best ask: {book['levels'][1][0]}")

# All mid prices
mids = info.all_mids()
print(f"ETH mid: {mids['ETH']}")

# Asset metadata
meta = info.meta()
for asset in meta["universe"]:
    if asset["name"] == "ETH":
        print(f"ETH tick size: {asset['szDecimals']} decimals")
```

## 3. Write the Strategy

Create `hyperdspy/strategies/volatility_mm.py`:

```python
from decimal import Decimal

from hyperdspy.models import (
    AccountState, BookSnapshot, DesiredOrder, Order,
    Side, StrategyDecision,
)
from hyperdspy.strategy import Strategy


class VolatilityMM(Strategy):
    """Market maker that widens spread when volatility increases.

    Tracks recent mid prices and uses the rolling range as a
    volatility proxy. Wider volatility = wider quotes = less adverse
    selection risk.
    """

    def __init__(
        self,
        base_spread_bps: Decimal = Decimal("5"),
        vol_multiplier: Decimal = Decimal("2"),
        order_size: Decimal = Decimal("0.01"),
        max_position: Decimal = Decimal("0.1"),
        lookback: int = 30,
    ):
        self.base_spread_bps = base_spread_bps
        self.vol_multiplier = vol_multiplier
        self.order_size = order_size
        self.max_position = max_position
        self.lookback = lookback
        self._mid_history: list[Decimal] = []

    def on_tick(self, coin, book, account, open_orders):
        if book is None or book.mid_price is None:
            return None

        mid = book.mid_price
        self._mid_history.append(mid)
        if len(self._mid_history) > self.lookback:
            self._mid_history = self._mid_history[-self.lookback:]

        # --- Volatility-adjusted spread ---
        if len(self._mid_history) >= 5:
            recent_high = max(self._mid_history)
            recent_low = min(self._mid_history)
            range_bps = (recent_high - recent_low) / mid * Decimal("10000")
            spread_bps = self.base_spread_bps + range_bps * self.vol_multiplier
        else:
            spread_bps = self.base_spread_bps

        half_spread = mid * spread_bps / Decimal("20000")

        # --- Inventory management ---
        position = account.positions.get(coin)
        pos_size = position.size if position else Decimal("0")

        # Skew quotes away from inventory
        skew = Decimal("0")
        if pos_size != 0:
            skew = pos_size / self.max_position * half_spread

        # Don't add to position if at max
        orders = []
        if pos_size < self.max_position:
            orders.append(DesiredOrder(Side.BID, mid - half_spread - skew, self.order_size))
        if pos_size > -self.max_position:
            orders.append(DesiredOrder(Side.ASK, mid + half_spread - skew, self.order_size))

        if not orders:
            return None

        return StrategyDecision(coin=coin, desired_orders=orders)

    def on_start(self, coins):
        print(f"VolatilityMM starting on {coins}")
        print(f"  base_spread: {self.base_spread_bps} bps")
        print(f"  order_size: {self.order_size}")
        print(f"  max_position: {self.max_position}")

    def on_stop(self):
        print("VolatilityMM stopped")
```

## 4. Run in Paper Mode

```python
# run_volatility_mm.py
from decimal import Decimal
from hyperdspy.config import load_config
from hyperdspy.engine import Engine
from hyperdspy.strategies.volatility_mm import VolatilityMM

config = load_config()
strategy = VolatilityMM(
    base_spread_bps=Decimal("8"),
    order_size=Decimal("0.01"),
    max_position=Decimal("0.05"),
)
engine = Engine(config, strategy)
engine.run()
```

```bash
uv run python run_volatility_mm.py
```

You'll see log output like:

```
12:00:01.000 [INFO] hyperdspy.engine: Starting engine: coins=['ETH'], mode=PAPER
12:00:01.500 [INFO] hyperdspy.engine: Seeded ETH book: mid=3450.50
VolatilityMM starting on ['ETH']
  base_spread: 8 bps
  order_size: 0.01
  max_position: 0.05
12:00:01.500 [INFO] hyperdspy.engine: Engine started. Entering tick loop.
```

Press Ctrl-C to stop. The engine cancels all orders and shuts down cleanly.

## 5. Analyze Recorded Data

After running for a while, load the recorded data:

```python
import pandas as pd
import matplotlib.pyplot as plt

# Load L2 data
l2 = pd.read_json("data/ETH/l2_2026-02-22.jsonl", lines=True)
l2["time"] = pd.to_datetime(l2["recv_ts_ms"], unit="ms")
l2["mid"] = l2["mid"].astype(float)
l2["spread_bps"] = l2["spread_bps"].astype(float)

# Plot mid price over time
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 6), sharex=True)
ax1.plot(l2["time"], l2["mid"])
ax1.set_ylabel("Mid Price")
ax1.set_title("ETH Market Data")

ax2.plot(l2["time"], l2["spread_bps"])
ax2.set_ylabel("Spread (bps)")
ax2.set_xlabel("Time")

plt.tight_layout()
plt.savefig("eth_analysis.png")
print(f"Records: {len(l2)}")
print(f"Avg spread: {l2['spread_bps'].mean():.2f} bps")
print(f"Price range: {l2['mid'].min():.2f} - {l2['mid'].max():.2f}")
```

Load trades:

```python
trades = pd.read_json("data/ETH/trades_2026-02-22.jsonl", lines=True)
trades["time"] = pd.to_datetime(trades["time"], unit="ms")
trades["px"] = trades["px"].astype(float)
trades["sz"] = trades["sz"].astype(float)

buys = trades[trades["side"] == "B"]
sells = trades[trades["side"] == "A"]
print(f"Buy volume:  {buys['sz'].sum():.2f} ETH")
print(f"Sell volume: {sells['sz'].sum():.2f} ETH")
print(f"Net flow:    {buys['sz'].sum() - sells['sz'].sum():.2f} ETH")
```

## 6. Tune Parameters

Based on the recorded data, adjust your strategy:

| Parameter | Effect |
|---|---|
| `base_spread_bps` | Wider = fewer fills but less adverse selection. Start wider (10-20 bps) and narrow |
| `vol_multiplier` | Higher = more aggressive widening during volatile periods |
| `order_size` | Smaller = less inventory risk per fill |
| `max_position` | Caps directional exposure |
| `tick_interval_s` | Faster = more responsive quotes but more cancellations |

## 7. Go Live

Once you're confident in the strategy:

1. **Start on testnet** -- set `base_url` to `https://api.hyperliquid-testnet.xyz`
2. **Use small sizes** -- reduce `order_size` and `max_position`
3. **Switch to mainnet** -- set `paper_mode: false` and use the mainnet URL

```json
{
    "paper_mode": false,
    "base_url": "https://api.hyperliquid.xyz",
    "coins": ["ETH"],
    "recording": {"enabled": true}
}
```

The framework handles graceful shutdown on Ctrl-C or SIGTERM -- all open orders are cancelled before exit.

## Key Considerations

**Market making risks:**
- Adverse selection: informed traders pick off your stale quotes
- Inventory risk: accumulating a large directional position during trends
- Latency: slower quote updates mean more exposure to price moves

**Framework safeguards:**
- `cancel_all_first=True` (default) ensures stale orders are removed before new quotes
- `max_position` in the strategy caps directional exposure
- Paper mode lets you test with real market dynamics
- Data recording enables post-session analysis and parameter tuning
- Signal handlers ensure clean shutdown with order cancellation
