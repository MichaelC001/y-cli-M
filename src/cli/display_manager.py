import re
import time
import asyncio
from typing import List, Tuple, Optional
from chat.models import Message
from config import config
from bot.models import BotConfig
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.theme import Theme
from rich.live import Live
from collections import deque
import sys
from rich.status import Status
from loguru import logger

# Custom theme for role-based colors
custom_theme = Theme({
    "user": "green",
    "assistant": "cyan",
    'system': "yellow",
    "tool": "blue",
    "timestamp": "dim white",
})

class StreamBuffer:
    def __init__(self, max_chars_per_second: int):
        self.buffer = ""
        self.max_chars_per_second = max_chars_per_second
        self.last_update_time = time.time()
        self.last_position = 0

    def add_content(self, content: str):
        self.buffer += content

    def get_next_chunk(self) -> str:
        current_time = time.time()
        time_diff = current_time - self.last_update_time
        max_chars = int(self.max_chars_per_second * time_diff)

        if max_chars > 0:
            chunk = self.buffer[self.last_position:self.last_position + max_chars]
            self.last_position += len(chunk)
            self.last_update_time = current_time
            return chunk
        return ""

    @property
    def has_remaining(self) -> bool:
        return self.last_position < len(self.buffer)

class DisplayManager:
    def __init__(self, bot_config: Optional[BotConfig] = None):
        self.console = Console(theme=custom_theme)
        self.max_chars_per_second = bot_config.print_speed if bot_config and bot_config.print_speed else 1000
        self.show_reasoning = bot_config.show_reasoning if bot_config and bot_config.show_reasoning is not None else False
        # Ensure console width is detected, especially if running in a non-standard terminal
        # self.console.size = self.console.size # Rich handles this automatically, explicit setting might not always be best
        logger.info("DisplayManager initialized.")

    def display_message_panel(self, message: Message, index: Optional[int] = None):
        logger.debug(f"display_message_panel called for role: {message.role}, already_displayed_live: {hasattr(message, 'already_displayed_live') and message.already_displayed_live}")
        if message.role == "assistant" and hasattr(message, 'already_displayed_live') and message.already_displayed_live:
            logger.info("display_message_panel: Assistant message already displayed live, skipping panel.")
            return

        timestamp = f"[timestamp]{message.timestamp}[/timestamp]"
        role = f"[{message.role}]{message.role.capitalize()}[/{message.role}]"
        index_str = f"[{index}] " if index is not None else ""

        # Add model/provider info if available
        model_info = ""
        if message.model:
            provider = f" @ {message.provider}" if message.provider else ""
            reasoning = f" (effort: {message.reasoning_effort})" if message.reasoning_effort else ""
            model_info = f" {message.model}{provider}{reasoning}"

        # Extract content text from structured content if needed
        content = message.content
        if isinstance(content, list):
            content = next((part.text for part in content if part.type == 'text'), '')

        # replace <thinking> and </thinking> with thinking emoji
        for tag in ['<thinking>', '</thinking>']:
            content = content.replace(tag, '🤔')

        # Construct display content with reasoning first
        display_content = ""
        if self.show_reasoning and message.reasoning_content:
            display_content = f"```markdown\n{message.reasoning_content}\n```\n"
        display_content += content

        # Add MCP server/tool info if available
        if message.role == "assistant" and (message.server or message.tool):
            mcp_info = "```\n"
            if message.server:
                mcp_info += f"Server: {message.server}\n"
            if message.tool:
                mcp_info += f"Tool: {message.tool}\n"
            if message.arguments:
                import json
                mcp_info += f"Arguments: {json.dumps(message.arguments, indent=2, ensure_ascii=False)}\n"
            mcp_info += "```\n"
            display_content += f"\n{mcp_info}"

        # Determine border style - change User to Assistant style if has MCP info
        border_style = message.role
        if message.role == "user" and (message.server or message.tool):
            role = f"[tool]Tool[tool]"
            border_style = "tool"  # Use Assistant color for User with MCP info
            model_info = f" {message.tool} @ {message.server}"  # Clear model info for User with MCP info

        self.console.print(Panel(
            Markdown(display_content),
            title=f"{index_str}{role} {timestamp}{model_info}",
            border_style=border_style
        ))

    async def _collect_stream_content(self, response_stream, stream_buffer: StreamBuffer) -> Tuple[str, str, Optional[str], Optional[str]]:
        """Collect content from the response stream, add to buffer, and extract metadata.
        Ensures all non-None string content (including empty strings) is collected.

        Args:
            response_stream: The streaming response from the provider (yields SimpleNamespace chunks)
            stream_buffer: The buffer to store content for rate-limited display

        Returns:
            Tuple[str, str, Optional[str], Optional[str]]: 
                (complete response text, reasoning text, provider_info, model_info)
        """
        all_content = "" # This variable is not used for the final return value, consider removing if truly unused.
        all_reasoning_content = "" # This variable is not used for the final return value, consider removing if truly unused.
        collected_content = [] 
        collected_reasoning_content = [] 
        is_reasoning_block = False
        
        provider_info_extracted: Optional[str] = None
        model_info_extracted: Optional[str] = None

        async for chunk_data_obj in response_stream: 
            if provider_info_extracted is None and hasattr(chunk_data_obj, 'provider') and chunk_data_obj.provider:
                provider_info_extracted = chunk_data_obj.provider
            if model_info_extracted is None and hasattr(chunk_data_obj, 'model') and chunk_data_obj.model:
                model_info_extracted = chunk_data_obj.model

            if not (hasattr(chunk_data_obj, 'choices') and chunk_data_obj.choices and hasattr(chunk_data_obj.choices[0], 'delta')):
                continue 

            delta = chunk_data_obj.choices[0].delta
            chunk_content = delta.content if hasattr(delta, 'content') else None
            chunk_reasoning = delta.reasoning_content if hasattr(delta, 'reasoning_content') else None
            
            # Log individual chunks for deeper inspection
            if chunk_content is not None:
                logger.trace(f"Collected content chunk: {repr(chunk_content)}")
            if chunk_reasoning is not None:
                logger.trace(f"Collected reasoning chunk: {repr(chunk_reasoning)}")

            new_display_chunk = ""

            if chunk_reasoning is not None: # Process if not None
                if not is_reasoning_block:
                    is_reasoning_block = True
                    if self.show_reasoning:
                        new_display_chunk += "> reasoning\n"
                if self.show_reasoning:
                    new_display_chunk += chunk_reasoning
                collected_reasoning_content.append(chunk_reasoning) # Collect all non-None reasoning

            if is_reasoning_block and chunk_reasoning is None and chunk_content is not None: # End of reasoning, start of summary (check Nones carefully)
                if self.show_reasoning:
                    new_display_chunk += "\n> summary\n"
                is_reasoning_block = False

            if chunk_content is not None: # Process if not None
                new_display_chunk += chunk_content
                collected_content.append(chunk_content) # Collect all non-None content, including empty strings

            if new_display_chunk: 
                stream_buffer.add_content(new_display_chunk)
        
        return "".join(collected_content), "".join(collected_reasoning_content), provider_info_extracted, model_info_extracted

    def _update_display_buffer(self, content_buffer: deque, new_content: str):
        """Update the display buffer with new content.

        Args:
            content_buffer: The deque buffer for display content
            new_content: New content to add to the buffer
        """
        first_part, *rest = new_content.split('\n')
        if not content_buffer:
            content_buffer.append(first_part)
        else:
            content_buffer[-1] += first_part
        content_buffer.extend(rest)

    async def stream_response(self, response_stream, model_name_for_status: Optional[str] = None) -> Tuple[str, str, Optional[str], Optional[str]]:
        """Stream and display the response in real-time.
        Handles an initial 'Thinking...' message with model name until first content arrives.
        Then, prints the complete message once fully received.
        Also extracts and returns provider and model metadata from the stream.

        Args:
            response_stream: The async generator streaming response chunks.
            model_name_for_status: Optional model name to display in the initial status message.

        Returns:
            Tuple[str, str, Optional[str], Optional[str]]: 
                (complete response text, reasoning text, provider_info, model_info)
        """
        # StreamBuffer is not directly used for display here but _collect_stream_content might use it.
        # For this simplified approach, we'll collect directly.
        # stream_buffer = StreamBuffer(max_chars_per_second=self.max_chars_per_second)

        all_collected_content: List[str] = []
        all_collected_reasoning: List[str] = []
        provider_info_from_stream: Optional[str] = None
        model_info_from_stream: Optional[str] = None
        is_reasoning_block = False # To manage reasoning/summary labels if shown

        status_text = f"[bold green]Thinking... {model_name_for_status if model_name_for_status else ''}"
        
        with Status(status_text.strip(), spinner="dots", console=self.console) as status:
            async for chunk_data_obj in response_stream:
                if provider_info_from_stream is None and hasattr(chunk_data_obj, 'provider') and chunk_data_obj.provider:
                    provider_info_from_stream = chunk_data_obj.provider
                if model_info_from_stream is None and hasattr(chunk_data_obj, 'model') and chunk_data_obj.model:
                    model_info_from_stream = chunk_data_obj.model
                    # Update status message once model is known, if not provided initially
                    if not model_name_for_status and model_info_from_stream:
                        status.update(f"[bold green]Receiving from {model_info_from_stream}...", spinner="dots")
                    elif model_name_for_status and model_info_from_stream and model_name_for_status != model_info_from_stream:
                        # If initial model was a guess/default and stream provides actual
                        status.update(f"[bold green]Receiving from {model_info_from_stream}...", spinner="dots")


                if not (hasattr(chunk_data_obj, 'choices') and chunk_data_obj.choices and hasattr(chunk_data_obj.choices[0], 'delta')):
                    continue

                delta = chunk_data_obj.choices[0].delta
                chunk_content = delta.content if hasattr(delta, 'content') else None
                chunk_reasoning = delta.reasoning_content if hasattr(delta, 'reasoning_content') else None

                if chunk_reasoning is not None:
                    if not is_reasoning_block: # First reasoning chunk
                        is_reasoning_block = True
                        if self.show_reasoning:
                            all_collected_content.append("> reasoning\n") # Add label if showing
                    all_collected_reasoning.append(chunk_reasoning)
                    if self.show_reasoning:
                        all_collected_content.append(chunk_reasoning) # Append to main display if shown

                # If reasoning block just ended (current chunk_reasoning is None but prev wasn't)
                # AND there's actual content in this chunk, it means summary is starting
                if is_reasoning_block and chunk_reasoning is None and chunk_content is not None:
                    if self.show_reasoning:
                         all_collected_content.append("\n> summary\n") # Add label
                    is_reasoning_block = False # Reset flag

                if chunk_content is not None:
                    all_collected_content.append(chunk_content)
        
        # --- Status context has ended ---
        logger.info("Response collection finished. Preparing for final print.")

        final_text_content = "".join(all_collected_content)
        final_reasoning_content = "".join(all_collected_reasoning) # This is the raw reasoning

        # Construct the display string (which might differ from final_text_content if reasoning isn't shown)
        # If reasoning is not shown, final_text_content already excludes reasoning markers and content.
        # If reasoning IS shown, final_text_content includes the markers and reasoning.
        # The goal is to display final_text_content.
        # The `full_reasoning_content` returned by the function should be the raw reasoning.
        
        display_markdown_string = final_text_content # This will be printed

        # logger.debug(f"Final display string for Markdown rendering (len: {len(display_markdown_string)}):\n{display_markdown_string}")

        if display_markdown_string.strip():
            logger.info("About to execute self.console.print(Markdown(display_markdown_string.strip())) for the FINAL message.")
            self.console.print(Markdown(display_markdown_string.strip()))
            logger.info("Finished self.console.print(Markdown(display_markdown_string.strip())) for the FINAL message.")
        else:
            logger.info("Final print: No response or empty response received.")
            self.console.print(Markdown("🤔 No response or empty response received."))

        # Return the raw full text (excluding any reasoning markers if reasoning wasn't shown)
        # and the raw full reasoning.
        # If self.show_reasoning is False, final_text_content will be just the summary.
        # If self.show_reasoning is True, final_text_content contains "> reasoning..." etc.
        # We need to decide what "full_text_content" for the return value means.
        # Let's assume it means the actual assistant's message content, without our added markers.
        
        # Reconstruct the "true" assistant message content if reasoning was shown and thus markers were added
        true_assistant_content = ""
        if self.show_reasoning:
            # Find summary part if it exists
            summary_marker = "\n> summary\n"
            if summary_marker in final_text_content:
                true_assistant_content = final_text_content.split(summary_marker, 1)[1]
            else: # It might have been all reasoning, or no markers were added
                true_assistant_content = "".join([c for c in all_collected_content if c not in ("> reasoning\n", "\n> summary\n") and not any(r_chunk in c for r_chunk in all_collected_reasoning)])
                if not true_assistant_content and not final_reasoning_content : # If all_collected_content was only markers
                     true_assistant_content = "".join(all_collected_content) # just use it as is
                elif not true_assistant_content and final_reasoning_content and not "".join(all_collected_content).strip().startswith("> reasoning"):
                    # This case means reasoning was collected, but not shown, so final_text_content is the true content
                     true_assistant_content = final_text_content

        else: # Reasoning not shown, so final_text_content is the true content
            true_assistant_content = final_text_content
            
        # If true_assistant_content is empty but full_reasoning_content exists, it means the LLM *only* provided reasoning.
        # In this scenario, the "true_assistant_content" should probably be the reasoning itself, or a note.
        # For now, let's prioritize reasoning if primary content is empty.
        if not true_assistant_content.strip() and final_reasoning_content.strip():
            true_assistant_content = final_reasoning_content # Or a message like "[Only reasoning content was provided]"

        return true_assistant_content, final_reasoning_content, provider_info_from_stream, model_info_from_stream

    def display_help(self):
        """Display help information about available commands and features"""
        help_content = """
[bold]Available Commands:[/bold]

• Enter 'exit' or 'quit' to end the conversation
• Enter your message and press Enter to send

[bold]Multi-line Input:[/bold]
1. Type <<EOF and press Enter
2. Type your multi-line message
3. Type EOF and press Enter to finish

[bold]Message Copying:[/bold]
• Messages are indexed starting from 0
• Use 'copy n' to copy message n (e.g., 'copy 0' for first message)
"""
        self.console.print(Panel(
            Markdown(help_content),
            title="[bold]Help Information[/bold]",
            border_style="yellow"
        ))

    def display_chat_history(self, messages: List[Message]):
        """Display the chat history, skipping system messages"""
        if messages:
            history_messages = [msg for msg in messages if msg.role != 'system']
            if history_messages:
                for i, message in enumerate(history_messages):
                    self.display_message_panel(message, index=i)
                self.console.print(Panel(
                    "[bold]Type your message to continue the conversation[/bold]",
                    border_style="yellow"
                ))

    def print_error(self, error: str, show_traceback: bool = False):
        """Display an error message with optional traceback in a panel"""
        error_content = f"[red]{error}[/red]"
        if show_traceback and hasattr(error, '__traceback__'):
            import traceback
            error_content += f"\n\n[red]Detailed error:\n{''.join(traceback.format_tb(error.__traceback__))}[/red]"

        self.console.print(Panel(
            Markdown(error_content),
            title="[red]Error[/red]",
            border_style="red"
        ))

    def clear_lines(self, lines: int):
        """Clear the specified number of lines using ANSI escape sequences

        Args:
            lines: Number of lines to clear
        """
        for _ in range(lines):
            sys.stdout.write("\033[F")   # Cursor up one line
