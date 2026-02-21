from hyperdspy.config import Config as Config
from hyperdspy.config import load_config


def main():
    """CLI entry point: `uv run dspy`"""
    from hyperdspy.engine import Engine
    from hyperdspy.strategies.simple_mm import SimpleMarketMaker

    config = load_config()
    strategy = SimpleMarketMaker()
    engine = Engine(config, strategy)
    engine.run()
