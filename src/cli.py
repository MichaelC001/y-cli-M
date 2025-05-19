import sys
import os
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))
# import importlib.util
# spec = importlib.util.find_spec("rich")
# print("USING RICH FROM:", spec.origin)
from loguru import logger

logger.remove()
logger.add(sys.stderr, level="INFO")

from cli import cli

if __name__ == "__main__":
    cli()
