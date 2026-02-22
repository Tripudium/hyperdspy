import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class WalletConfig:
    secret_key: str
    account_address: str
    vault_address: Optional[str] = None


@dataclass(frozen=True)
class TradingConfig:
    coins: list[str] = field(default_factory=lambda: ["BTC"])
    leverage: int = 20
    is_cross: bool = True
    max_position_usd: float = 1000.0


@dataclass(frozen=True)
class RecordingConfig:
    enabled: bool = False
    output_dir: str = "data"
    format: str = "jsonl"  # "jsonl" or "csv"
    record_l2: bool = True
    record_l4: bool = True
    record_trades: bool = True


@dataclass(frozen=True)
class Config:
    wallet: WalletConfig
    trading: TradingConfig
    base_url: str = "https://api.hyperliquid.xyz"
    paper_mode: bool = False
    log_level: str = "INFO"
    tick_interval_s: float = 1.0
    l4_server_url: Optional[str] = None  # e.g. "ws://localhost:8000/ws"
    recording: RecordingConfig = field(default_factory=RecordingConfig)


def load_config(path: Path = Path("config.json")) -> Config:
    """Load config.json and return a validated Config object.

    Required fields: secret_key, account_address
    Optional fields: base_url, paper_mode, coins, leverage, max_position_usd,
                     tick_interval_s, log_level, vault_address
    """
    raw = json.loads(path.read_text())

    wallet = WalletConfig(
        secret_key=raw["secret_key"],
        account_address=raw["account_address"],
        vault_address=raw.get("vault_address"),
    )

    trading = TradingConfig(
        coins=raw.get("coins", ["BTC"]),
        leverage=raw.get("leverage", 20),
        is_cross=raw.get("is_cross", True),
        max_position_usd=raw.get("max_position_usd", 1000.0),
    )

    rec_raw = raw.get("recording", {})
    recording = RecordingConfig(
        enabled=rec_raw.get("enabled", False),
        output_dir=rec_raw.get("output_dir", "data"),
        format=rec_raw.get("format", "jsonl"),
        record_l2=rec_raw.get("record_l2", True),
        record_l4=rec_raw.get("record_l4", True),
        record_trades=rec_raw.get("record_trades", True),
    )

    return Config(
        wallet=wallet,
        trading=trading,
        base_url=raw.get("base_url", "https://api.hyperliquid.xyz"),
        paper_mode=raw.get("paper_mode", False),
        log_level=raw.get("log_level", "INFO"),
        tick_interval_s=raw.get("tick_interval_s", 1.0),
        l4_server_url=raw.get("l4_server_url"),
        recording=recording,
    )
