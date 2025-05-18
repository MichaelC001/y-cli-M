import os
import asyncio
import click
from typing import Optional
from rich.console import Console

from chat.app import ChatApp
from cli.display_manager import custom_theme
from config import bot_service, config
from loguru import logger
from bot.models import BotConfig
from chat.service import ChatService
from chat.repository import get_chat_repository
from util import generate_id

@click.command()
@click.option('--chat-id', '-c', help='Continue from an existing chat')
@click.option('--latest', '-l', is_flag=True, help='Continue from the latest chat')
@click.option('--model', '-m', help='OpenRouter model to use (overrides bot config)')
@click.option('--verbose', '-v', is_flag=True, help='Show detailed usage instructions')
@click.option('--bot', '-b', help='Use specific bot name')
@click.option('--show-reasoning', is_flag=True, default=None, help='Show AI reasoning/thinking steps (overrides bot config)')
def chat(chat_id: Optional[str], latest: bool, model: Optional[str], verbose: bool = False, bot: Optional[str] = None, show_reasoning: Optional[bool] = None):
    """Interactive chat with AI"""
    loaded_bot_config: Optional[BotConfig] = None

    if bot:
        loaded_bot_config = bot_service.get_config(bot)
        if not loaded_bot_config:
            logger.error(f"Bot configuration '{bot}' not found.")
            return
    elif model:
        all_bots = bot_service.list_configs()
        # Prefer a bot that explicitly uses this model
        loaded_bot_config = next((b for b in all_bots if b.model == model), None)
        if not loaded_bot_config and all_bots: # Fallback to default or first if model-specific bot not found
            loaded_bot_config = bot_service.get_config("default") or all_bots[0]
            logger.info(f"No bot found configured for model {model}. Using bot '{loaded_bot_config.name}' and overriding its model.")
    else:
        loaded_bot_config = bot_service.get_config("default")
        if not loaded_bot_config:
            all_bots = bot_service.list_configs()
            if all_bots:
                loaded_bot_config = all_bots[0]
                logger.info(f"Default bot not found, using first available: {loaded_bot_config.name}")

    if not loaded_bot_config:
        logger.info("No bot configurations found or usable. Creating a temporary default configuration.")
        # Ensure all required fields for BotConfig have default values or are handled here
        loaded_bot_config = BotConfig(
            name="temporary_default",
            model=model if model else "gpt-4o", # Default model
            # Ensure other BotConfig fields like api_key etc. are handled if they don't have defaults
        )
    
    # Apply overrides from command line options
    if model:
        loaded_bot_config.model = model
    
    if show_reasoning is not None: # Flag was explicitly used
        loaded_bot_config.show_reasoning = show_reasoning
    elif loaded_bot_config.show_reasoning is None: # Flag not used, and field is None in config (e.g. old config)
        loaded_bot_config.show_reasoning = False # Default to False

    chat_id_to_load = None
    if chat_id:
        chat_id_to_load = chat_id
    elif latest:
        chat_repo = get_chat_repository()
        chat_service = ChatService(repository=chat_repo)
        latest_chats = asyncio.run(chat_service.list_chats(limit=1))
        if latest_chats:
            chat_id_to_load = latest_chats[0].id
            logger.info(f"Continuing from latest chat: {chat_id_to_load}")
        else:
            logger.info("No previous chats found to continue from.")
    
    if not chat_id_to_load:
        chat_id_to_load = generate_id()
        logger.info(f"Starting new chat: {chat_id_to_load}")

    chat_app = ChatApp(bot_config=loaded_bot_config, chat_id=chat_id_to_load, verbose=verbose)
    asyncio.run(chat_app.chat())
