from typing import Optional
from config import config
from .base import ChatRepository
from .file import FileRepository
from .cloudflare import CloudflareRepository


def get_chat_repository() -> ChatRepository:
    """
    Factory function to get the appropriate chat repository implementation
    based on configuration.
    
    Returns:
        ChatRepository: An instance of the configured repository implementation
    """
    # Check if Cloudflare storage is enabled
    storage_type = config.get('storage_type', 'file')
    
    if storage_type == 'cloudflare':
        # print("Using Cloudflare storage")
        # Ensure required Cloudflare config is present
        cloudflare_config = config.get('cloudflare', {})
        required_keys = ['account_id', 'api_token', 'kv_namespace_id']
        
        if all(key in cloudflare_config for key in required_keys):
            return CloudflareRepository()
        else:
            missing = [key for key in required_keys if key not in cloudflare_config]
            print(f"Warning: Missing Cloudflare configuration: {', '.join(missing)}")
            print("Falling back to file-based storage")
    
    # Default to file-based repository
    return FileRepository()
