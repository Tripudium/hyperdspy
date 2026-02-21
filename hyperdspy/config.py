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
class Config:
    wallet: WalletConfig
    trading: TradingConfig
    base_url: str = "https://api.hyperliquid.xyz"
    paper_mode: bool = False
    log_level: str = "INFO"
    tick_interval_s: float = 1.0


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

    return Config(
        wallet=wallet,
        trading=trading,
        base_url=raw.get("base_url", "https://api.hyperliquid.xyz"),
        paper_mode=raw.get("paper_mode", False),
        log_level=raw.get("log_level", "INFO"),
        tick_interval_s=raw.get("tick_interval_s", 1.0),
    )
