import click
from typing import Optional
from bot import BotConfig
from config import bot_service, config

@click.command('add')
@click.option('--reasoning-effort', help='Set reasoning effort for the bot.')
@click.option('--show-reasoning', is_flag=True, help='Default to showing reasoning for this bot.')
def bot_add(name: Optional[str], base_url: Optional[str], api_key: Optional[str], api_type: Optional[str], model: Optional[str], print_speed: Optional[int], description: Optional[str], openrouter_config: Optional[str], prompts: Optional[str], mcp_servers: Optional[str], max_tokens: Optional[int], custom_api_path: Optional[str], reasoning_effort: Optional[str], show_reasoning: bool):
    """Add a new bot configuration."""
    # Tip about direct file editing
    click.echo(f"TIP: For efficiency, you can directly edit the bot configuration file at: {config['bot_config_file']}")
    
    # Check if bot already exists
    existing_configs = bot_service.list_configs()
    if any(config.name == name for config in existing_configs):
        if not click.confirm(f"Bot '{name}' already exists. Do you want to overwrite it?"):
            click.echo("Operation cancelled")
            return
    
    # Get default config for default values
    default_config = bot_service.default_config
            
    # Proceed with collecting remaining details
    api_key = api_key if api_key is not None else default_config.api_key
    base_url = base_url if base_url is not None else default_config.base_url
    model = model if model is not None else default_config.model
    print_speed = print_speed if print_speed is not None else default_config.print_speed
    description = description if description is not None else default_config.description
    openrouter_config = openrouter_config if openrouter_config is not None else default_config.openrouter_config
    prompts = prompts if prompts is not None else default_config.prompts
    mcp_servers = mcp_servers if mcp_servers is not None else default_config.mcp_servers
    max_tokens = max_tokens if max_tokens is not None else default_config.max_tokens
    custom_api_path = custom_api_path if custom_api_path is not None else default_config.custom_api_path
    reasoning_effort = reasoning_effort if reasoning_effort is not None else default_config.reasoning_effort
    show_reasoning = show_reasoning if show_reasoning is not None else default_config.show_reasoning

    bot_config = BotConfig(name=name, api_key=api_key, base_url=base_url, model=model, print_speed=print_speed, description=description, openrouter_config=openrouter_config, prompts=prompts, mcp_servers=mcp_servers, max_tokens=max_tokens, custom_api_path=custom_api_path, reasoning_effort=reasoning_effort, show_reasoning=show_reasoning)
    bot_service.add_config(bot_config)
    click.echo(f"Bot '{name}' added successfully")
