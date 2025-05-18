from typing import List, Dict, Optional, AsyncGenerator, Tuple
from .base_provider import BaseProvider
from .display_manager_mixin import DisplayManagerMixin
import json
from types import SimpleNamespace
import httpx
from chat.models import Message, Chat
from bot.models import BotConfig
from ..utils.message_utils import create_message

class OpenAIFormatProvider(BaseProvider, DisplayManagerMixin):
    def __init__(self, bot_config: BotConfig):
        """Initialize OpenRouter settings.

        Args:
            bot_config: Bot configuration containing API settings
        """
        DisplayManagerMixin.__init__(self)
        self.bot_config = bot_config

    def prepare_messages_for_completion(self, messages: List[Message], system_prompt: Optional[str] = None) -> List[Dict]:
        """Prepare messages for completion by adding system message and cache_control.

        Args:
            messages: Original list of Message objects
            system_prompt: Optional system message to add at the start

        Returns:
            List[Dict]: New message list with system message and cache_control added
        """
        # Create new list starting with system message if provided
        prepared_messages = []
        if system_prompt:
            system_message = create_message('system', system_prompt)
            system_message_dict = system_message.to_dict()
            if isinstance(system_message_dict["content"], str):
                system_message_dict["content"] = [{"type": "text", "text": system_message_dict["content"]}]
            # Remove timestamp fields, otherwise likely unsupported_country_region_territory
            system_message_dict.pop("timestamp", None)
            system_message_dict.pop("unix_timestamp", None)
            # add cache_control only to claude-3 series model
            if "claude-3" in self.bot_config.model:
                for part in system_message_dict["content"]:
                    if part.get("type") == "text":
                        part["cache_control"] = {"type": "ephemeral"}
            prepared_messages.append(system_message_dict)

        # Add original messages
        for msg in messages:
            msg_dict = msg.to_dict()
            if isinstance(msg_dict["content"], list):
                msg_dict["content"] = [dict(part) for part in msg_dict["content"]]
            # Remove timestamp fields, otherwise likely unsupported_country_region_territory
            msg_dict.pop("timestamp", None)
            msg_dict.pop("unix_timestamp", None)
            prepared_messages.append(msg_dict)

        # Find last user message
        if "claude-3" in self.bot_config.model:
            for msg in reversed(prepared_messages):
                if msg["role"] == "user":
                    if isinstance(msg["content"], str):
                        msg["content"] = [{"type": "text", "text": msg["content"]}]
                    # Add cache_control to last text part
                    text_parts = [part for part in msg["content"] if part.get("type") == "text"]
                    if text_parts:
                        last_text_part = text_parts[-1]
                    else:
                        last_text_part = {"type": "text", "text": "..."}
                        msg["content"].append(last_text_part)
                    last_text_part["cache_control"] = {"type": "ephemeral"}
                    break

        return prepared_messages

    async def call_chat_completions(self, messages: List[Message], chat: Optional[Chat] = None, system_prompt: Optional[str] = None) -> Tuple[AsyncGenerator, Optional[str]]:
        """Get a streaming chat response from OpenRouter.

        Args:
            messages: List of Message objects
            system_prompt: Optional system prompt to add at the start

        Returns:
            Tuple[AsyncGenerator, Optional[str]]: An async generator yielding response chunks, and an optional external ID.

        Raises:
            Exception: If API call fails
        """
        # Prepare messages with cache_control and system message
        prepared_messages = self.prepare_messages_for_completion(messages, system_prompt)
        body = {
            "model": self.bot_config.model,
            "messages": prepared_messages,
            "stream": True
        }
        if "deepseek-r1" in self.bot_config.model:
            body["include_reasoning"] = True
        if self.bot_config.openrouter_config and "provider" in self.bot_config.openrouter_config:
            body["provider"] = self.bot_config.openrouter_config["provider"]
        if self.bot_config.max_tokens:
            body["max_tokens"] = self.bot_config.max_tokens
        if self.bot_config.reasoning_effort:
            body["reasoning_effort"] = self.bot_config.reasoning_effort
        
        # We will return the generator and the external_id (which is None for this provider currently)
        # The actual streaming and message creation will be handled by ChatManager
        async def stream_generator():
            try:
                async with httpx.AsyncClient(
                    base_url=self.bot_config.base_url,
                ) as client:
                    async with client.stream(
                        "POST",
                        self.bot_config.custom_api_path if self.bot_config.custom_api_path else "/chat/completions",
                        headers={
                            "HTTP-Referer": "https://luohy15.com",
                            'X-Title': 'y-cli',
                            "Authorization": f"Bearer {self.bot_config.api_key}",
                            "Content-Type": "application/json",
                        },
                        json=body,
                        timeout=60.0
                    ) as response:
                        response.raise_for_status()

                        provider_info = None # Changed from provider to provider_info to avoid confusion
                        model_info = None # Changed from model to model_info

                        async for chunk in response.aiter_lines():
                            if chunk.startswith("data: "):
                                try:
                                    data = json.loads(chunk[6:])
                                    if provider_info is None and data.get("provider"):
                                        provider_info = data["provider"]
                                    if model_info is None and data.get("model"):
                                        model_info = data["model"]

                                    if data.get("choices"):
                                        delta = data["choices"][0].get("delta", {})
                                        content = delta.get("content")
                                        reasoning_content = delta.get("reasoning_content") if delta.get("reasoning_content") else delta.get("reasoning")
                                        if content is not None or reasoning_content is not None:
                                            chunk_data = SimpleNamespace(
                                                choices=[SimpleNamespace(
                                                    delta=SimpleNamespace(content=content, reasoning_content=reasoning_content)
                                                )],
                                                model=model_info,
                                                provider=provider_info
                                            )
                                            yield chunk_data
                                except json.JSONDecodeError:
                                    continue
            except httpx.HTTPError as e:
                # Instead of raising, yield an error object or re-raise if ChatManager can handle it
                # For now, let it propagate to be caught by ChatManager
                raise Exception(f"HTTP error getting chat response: {str(e)}")
            except Exception as e:
                raise Exception(f"Error getting chat response: {str(e)}")

        return stream_generator(), None # external_id is None for this provider as per original logic

    async def translate_text(self, text: str, target_language: str) -> Optional[str]:
        """Translate text using the OpenAI-compatible endpoint.

        Args:
            text: The text to translate
            target_language: The target language for translation

        Returns:
            Optional[str]: The translated text or None if translation fails
        """
        translate_system_prompt = f"You are a translation engine. Translate the user's text to {target_language}. Output ONLY the translated text, without any introductory phrases, explanations, or the original text."
        translate_user_message = create_message('user', text)

        # Prepare messages
        prepared_messages = [
            create_message('system', translate_system_prompt).to_dict(),
            translate_user_message.to_dict()
        ]
        # Remove timestamp and potentially content list wrapping for simple translation
        for msg in prepared_messages:
            msg.pop("timestamp", None)
            msg.pop("unix_timestamp", None)
            # Ensure content is string for translation prompt
            if isinstance(msg.get("content"), list):
                msg["content"] = next((part.get("text") for part in msg["content"] if part.get("type") == "text"), "")

        body = {
            "model": self.bot_config.model, # Use the same configured model
            "messages": prepared_messages,
            "stream": False, # No need to stream for translation
            "temperature": 0.2, # Lower temperature for more deterministic translation
        }
        # Optional: Add provider, max_tokens if necessary based on config
        if self.bot_config.openrouter_config and "provider" in self.bot_config.openrouter_config:
            body["provider"] = self.bot_config.openrouter_config["provider"]
        if self.bot_config.max_tokens:
            body["max_tokens"] = self.bot_config.max_tokens # Adjust if needed for translation length

        try:
            async with httpx.AsyncClient(
                base_url=self.bot_config.base_url,
            ) as client:
                response = await client.post(
                    self.bot_config.custom_api_path if self.bot_config.custom_api_path else "/chat/completions",
                    headers={
                        "HTTP-Referer": "https://luohy15.com",
                        'X-Title': 'y-cli-translate', # Indicate translation context
                        "Authorization": f"Bearer {self.bot_config.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                    timeout=30.0 # Shorter timeout for translation
                )
                response.raise_for_status()
                result = response.json()
                if result.get("choices") and result["choices"][0].get("message"):
                    translated_content = result["choices"][0]["message"]["content"]
                    return translated_content.strip()
                else:
                    # Log unexpected response format
                    print(f"Unexpected translation response format: {result}")
                    return None
        except httpx.HTTPError as e:
            print(f"HTTP error during translation: {str(e)}") # Print error instead of raising
            return None
        except Exception as e:
            print(f"Error during translation: {str(e)}")
            return None
