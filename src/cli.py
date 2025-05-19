import sys
import os
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))
# import importlib.util
# spec = importlib.util.find_spec("rich")
# print("USING RICH FROM:", spec.origin)
from loguru import logger

# Custom filter to remove MCP tool execution log messages
def mcp_filter(record):
    # Filter out "Executing MCP tool" messages
    if "Executing MCP tool" in record["message"]:
        return False
    return True

logger.remove()
# Add stderr handler with filter
logger.add(sys.stderr, level="INFO", filter=mcp_filter)

from cli import cli

if __name__ == "__main__":
    cli()
