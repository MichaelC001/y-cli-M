import json
import os
import hashlib
from typing import List, Optional
from datetime import datetime
import aiofiles
from chat.models import Chat, Message
from config import config
from . import ChatRepository
from .cloudflare_client import CloudflareClient
from loguru import logger

local_chat_file_content = None

class CloudflareRepository(ChatRepository):
    """Chat repository implementation using Cloudflare KV and R2 with local caching"""
    
    def __init__(self):
        self.cf_client = CloudflareClient()
        self.local_cache_file = config.get('chat_file')
        # In-memory cache for recently written chats to handle read-after-write consistency
        self.memory_cache = {}
    
    def _calculate_checksum(self, content: str) -> str:
        """Calculate SHA-256 checksum of content"""
        return hashlib.sha256(content.encode('utf-8')).hexdigest()
    
    async def _get_kv_version(self) -> Optional[str]:
        """Get the version/checksum from KV"""
        return await self.cf_client.kv_get('chat_ver')
    
    async def _get_r2_version(self) -> Optional[str]:
        """Get the version/checksum from R2 (fallback)"""
        return await self.cf_client.r2_get('chat_ver')
    
    async def _set_kv_version(self, checksum: str) -> bool:
        """Set the version/checksum in KV"""
        return await self.cf_client.kv_put('chat_ver', checksum)
    
    async def _set_r2_version(self, checksum: str) -> bool:
        """Set the version/checksum in R2"""
        return await self.cf_client.r2_put('chat_ver', checksum)
    
    async def _read_local_cache(self) -> Optional[str]:
        """Read content from local cache file"""
        if not os.path.exists(self.local_cache_file):
            return None
        
        global local_chat_file_content
        if local_chat_file_content is None:
            # Read from file
            async with aiofiles.open(self.local_cache_file, "r", encoding="utf-8") as f:
                local_chat_file_content = await f.read()
        return local_chat_file_content
        
    async def _write_local_cache(self, content: str) -> bool:
        """Write content to local cache file"""
        async with aiofiles.open(self.local_cache_file, "w", encoding="utf-8") as f:
            await f.write(content)
        global local_chat_file_content
        local_chat_file_content = content
    
    async def _read_chats(self) -> List[Chat]:
        """
        Read all chats with the following strategy:
        1. Read from local cache (complete history)
        2. Read from KV (recent changes)
        3. Combine local and KV data, with KV taking precedence
        """
        # Read from local cache (complete history)
        local_chats = await self._read_chats_from_local_cache()
        # print(f"Read {len(local_chats)} chats from local cache")
        
        # Read from KV (recent changes)
        kv_chats = await self._read_from_kv()
        # print(f"Read {len(kv_chats)} chats from KV")
        
        # Combine local and KV data, with KV taking precedence
        # Create a dictionary of chats by ID for easy lookup
        chats_by_id = {chat.id: chat for chat in local_chats}
        
        # Update or add chats from KV
        for kv_chat in kv_chats:
            chats_by_id[kv_chat.id] = kv_chat
        
        # Finally, overlay any chats from the in-memory cache (highest precedence)
        for chat_id, cache_entry in self.memory_cache.items():
            chats_by_id[chat_id] = cache_entry['chat']
        
        # Convert back to list
        combined_chats = list(chats_by_id.values())
        return combined_chats
    
    async def _sync_from_r2_if_needed(self) -> None:
        """Check if local cache needs to be synced from R2"""
        # First try to get version from KV (faster)
        version = await self._get_kv_version()
        
        # If not in KV, fall back to R2
        if not version:
            version = await self._get_r2_version()
            if not version:
                print("No version found in KV or R2, skipping sync")
                return
        
        # Read local cache
        local_content = await self._read_local_cache()
        if not local_content:
            print("No local cache found, syncing from R2")
            await self._sync_from_r2()
            return
        
        # Compare checksums
        local_checksum = self._calculate_checksum(local_content)
        if local_checksum != version:
            print("Local cache outdated, syncing from R2")
            await self._sync_from_r2()
    
    async def _sync_from_r2(self) -> None:
        """Sync local cache from R2"""
        r2_content = await self.cf_client.r2_get('chat.jsonl')
        if r2_content:
            await self._write_local_cache(r2_content)
    
    async def _read_chats_from_local_cache(self) -> List[Chat]:
        """Read chats from local cache"""
        local_content = await self._read_local_cache()
        if not local_content:
            return []
        
        # Parse each line as a JSON object
        chat_dicts = []
        for line in local_content.splitlines():
            if line.strip():  # Skip empty lines
                try:
                    chat_dict = json.loads(line)
                    chat_dicts.append(chat_dict)
                except json.JSONDecodeError:
                    # Log or handle invalid JSON
                    continue
        
        return [Chat.from_dict(chat_dict) for chat_dict in chat_dicts]
    
    async def _read_from_kv(self) -> List[Chat]:
        """Read recent chats from KV"""
        kv_content = await self.cf_client.kv_get('chats')
        if not kv_content:
            return []
        
        # Parse each line as a JSON object
        chat_dicts = []
        for line in kv_content.splitlines():
            if line.strip():  # Skip empty lines
                try:
                    chat_dict = json.loads(line)
                    chat_dicts.append(chat_dict)
                except json.JSONDecodeError:
                    # Log or handle invalid JSON
                    print(f"Invalid JSON in KV: {line}")
                    continue
        
        return [Chat.from_dict(chat_dict) for chat_dict in chat_dicts]
    
    async def _write_chats(self, chats: List[Chat]) -> None:
        """
        Write chats with the following strategy:
        1. Write to KV (recent changes only, exclude existing_chats from local cache)
        
        Note: Local cache and R2 version are managed separately:
        - Local cache is updated when syncing from R2
        - R2 is updated by the Cloudflare Worker (cloudflare-worker.js)
        """
        # Get existing chats from local cache
        existing_chats = await self._read_chats_from_local_cache()
        
        # Create a dictionary of existing chats by ID for comparison
        existing_chats_by_id = {chat.id: chat for chat in existing_chats}
        
        # Identify chats that are new or modified
        modified_chats = []
        for chat in chats:
            # If chat doesn't exist in local cache, it's new
            if chat.id not in existing_chats_by_id:
                modified_chats.append(chat)
                continue
            
            # If chat exists but has been modified, include it
            # Note: This is a simplified comparison. In a real implementation,
            # you might want to compare specific fields or use a more sophisticated
            # comparison method.
            existing_chat = existing_chats_by_id[chat.id]
            if len(chat.messages) != len(existing_chat.messages):
                modified_chats.append(chat)
                continue
            
            # Additional comparison logic could be added here
        
        # If there are no modified chats, nothing to write to KV
        if not modified_chats:
            print("No new or modified chats to write to KV")
            return
        
        # Write only the modified chats to KV
        modified_json_lines = [json.dumps(chat.to_dict()) for chat in modified_chats]
        modified_str = '\n'.join(modified_json_lines)
        await self.cf_client.kv_put('chats', modified_str)
        # print(f"Wrote {len(modified_chats)} new or modified chats to KV")
    
    async def list_chats(self, keyword: Optional[str] = None, model: Optional[str] = None,
                   provider: Optional[str] = None, limit: int = 10) -> List[Chat]:
        """List chats with optional filtering

        Args:
            keyword: Optional text to filter messages by content
            model: Optional model name to filter by
            provider: Optional provider name to filter by
            limit: Maximum number of chats to return (default: 10)
        """
        chats = await self._read_chats()

        # Sort by create_time in descending order
        chats.sort(key=lambda x: x.create_time, reverse=True)

        # Apply filters if any are specified
        if any([keyword, model, provider]):
            filtered_chats = []
            for chat in chats:
                # Check each message in the chat
                for msg in chat.messages:
                    matches = True
                    
                    # Apply keyword filter if specified
                    if keyword:
                        keyword_lower = keyword.lower()
                        content_matches = False
                        if isinstance(msg.content, str):
                            if keyword_lower in msg.content.lower():
                                content_matches = True
                        else:  # content is a list of parts
                            for part in msg.content:
                                if isinstance(part, dict) and 'text' in part:
                                    if keyword_lower in part['text'].lower():
                                        content_matches = True
                                        break
                        if not content_matches:
                            matches = False
                            continue
                    
                    # Apply model filter if specified
                    if model and (not msg.model or model.lower() not in msg.model.lower()):
                        matches = False
                        continue
                    
                    # Apply provider filter if specified
                    if provider and (not msg.provider or provider.lower() not in msg.provider.lower()):
                        matches = False
                        continue
                    
                    # If all specified filters match, add the chat and break
                    if matches:
                        filtered_chats.append(chat)
                        break
                
                if len(filtered_chats) >= limit:
                    break
            
            chats = filtered_chats

        return chats[:limit]
    
    async def get_chat(self, chat_id: str) -> Optional[Chat]:
        """Get a specific chat by ID"""
        if chat_id in self.memory_cache:
            cache_entry = self.memory_cache[chat_id]
            return cache_entry['chat']
        
        # If not in cache or expired, read from storage
        chats = await self._read_chats()
        return next((chat for chat in chats if chat.id == chat_id), None)

    async def add_chat(self, chat: Chat) -> Chat:
        """Add a new chat"""
        chats = await self._read_chats()
        chats.append(chat)
        await self._write_chats(chats)
        # Add to recent writes cache with timestamp
        self.memory_cache[chat.id] = {
            'chat': chat,
            'timestamp': datetime.now().timestamp()
        }
        return chat

    async def update_chat(self, chat: Chat) -> Chat:
        """Update an existing chat"""
        chats = await self._read_chats()
        for i, existing_chat in enumerate(chats):
            if existing_chat.id == chat.id:
                chats[i] = chat
                await self._write_chats(chats)
                # Add to recent writes cache with timestamp
                self.memory_cache[chat.id] = {
                    'chat': chat,
                    'timestamp': datetime.now().timestamp()
                }
                return chat
        raise ValueError(f"Chat with id {chat.id} not found")

    async def delete_chat(self, chat_id: str) -> bool:
        """Delete a chat by ID"""
        chats = await self._read_chats()
        initial_length = len(chats)
        chats = [chat for chat in chats if chat.id != chat_id]
        if len(chats) < initial_length:
            await self._write_chats(chats)
            # Remove from recent writes cache if present
            if chat_id in self.memory_cache:
                del self.memory_cache[chat_id]
            return True
        return False
