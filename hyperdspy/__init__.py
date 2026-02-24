from hyperdspy.config import Config as Config
from hyperdspy.config import load_config
from hyperdspy.engine import Engine
from hyperdspy.strategies.simple_mm import SimpleMarketMaker


def main():
    """CLI entry point: `uv run dspy`"""
    
    config = load_config()
    strategy = SimpleMarketMaker()
    engine = Engine(config, strategy)
    engine.run()
