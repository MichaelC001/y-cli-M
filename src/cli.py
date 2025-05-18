import sys
from loguru import logger

logger.remove()
logger.add(sys.stderr, level="INFO")

from cli import cli

if __name__ == "__main__":
    cli()
