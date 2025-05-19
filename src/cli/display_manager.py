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
import os

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
        logger.debug("DisplayManager initialized.")
        # Buffer tracking for tool calls
        self.in_tool_call_block = False
        self.buffer = ""

    def display_message_panel(self, message: Message, index: Optional[int] = None):
        logger.debug(f"display_message_panel called for role: {message.role}, already_displayed_live: {hasattr(message, 'already_displayed_live') and message.already_displayed_live}")
        if message.role == "assistant" and hasattr(message, 'already_displayed_live') and message.already_displayed_live:
            logger.debug("display_message_panel: Assistant message already displayed live, skipping panel.")
            return

        # Hide MCP tool call/response details from terminal output (line-based)
        def should_hide_line(line: str) -> bool:
            # Only hide lines containing 'Executing MCP tool', not 'Tool use confirm'
            hide_patterns = [
                'Executing MCP tool',
            ]
            for p in hide_patterns:
                if p in line or line.strip().startswith(p) or line.strip().endswith(p):
                    return True
            # Hide lines that are just tool/process info markers (e.g., ===hide left===)
            if re.match(r'^=+hide( left| right)?=+$', line.strip()):
                return True
            return False

        # Aggressively remove all MCP/tool/process info from content
        def clean_mcp_info(text: str) -> str:
            # Remove all <use_mcp_tool>...</use_mcp_tool> blocks (robust, multiline, any whitespace, even if inline)
            text = re.sub(r'<use_mcp_tool>[\s\S]*?</use_mcp_tool>', '', text, flags=re.DOTALL)
            # Remove any lines containing <use_mcp_tool or </use_mcp_tool> (even if malformed)
            text = '\n'.join([line for line in text.splitlines() if '<use_mcp_tool' not in line and '</use_mcp_tool' not in line])
            # Remove any lines mentioning use_mcp_tool or use-mcp-tool in any context
            text = '\n'.join([line for line in text.splitlines() if 'use_mcp_tool' not in line and 'use-mcp-tool' not in line])
            return text

        # If the message content is a list, join it for pattern matching
        content = message.content
        if isinstance(content, list):
            content = '\n'.join(str(part.text) for part in content if hasattr(part, 'text'))
        if not content:
            return
        # Clean MCP/tool/process info aggressively
        content = clean_mcp_info(content)
        # Now split into lines and filter out lines containing 'Executing MCP tool' and any empty lines
        filtered_lines = [line for line in content.splitlines() if 'Executing MCP tool' not in line and line.strip()]
        filtered_content = '\n'.join(filtered_lines).strip()
        if not filtered_content:
            return  # Do not print if nothing remains
        # Use filtered_content for display
        display_content = filtered_content

        timestamp = f"[timestamp]{message.timestamp}[/timestamp]"
        index_str = f"[{index}] " if index is not None else ""

        # Initialize title components
        panel_role_display_text = ""
        current_border_style = message.role # Default border
        model_info = "" # Default model info for title

        # Determine role text, border style, and model_info for the panel title
        if message.role == "user":
            if message.server or message.tool: # User message is a tool result
                panel_role_display_text = f"[tool]Tool[/tool]"
                current_border_style = "tool" # Blue border for tool messages
                model_info = f" {message.tool} @ {message.server}" # Show tool@server
            else: # Normal user message
                panel_role_display_text = f"[timestamp]Michael[/timestamp]" # Dim white "Michael"
                if index is not None:
                    index_str = f"[timestamp][{index}] [/timestamp]" # Apply timestamp style
                # current_border_style remains "user" (green)
                # model_info remains empty for normal user messages
        elif message.role == "assistant":
            panel_role_display_text = f"[{message.role}]{message.role.capitalize()}[/{message.role}]"
            # current_border_style remains "assistant" (cyan)
            if message.model: # Add model/provider info for assistant
                provider_info_str = f" @ {message.provider}" if message.provider else ""
                reasoning_effort_str = f" (effort: {message.reasoning_effort})" if message.reasoning_effort else ""
                model_info = f" {message.model}{provider_info_str}{reasoning_effort_str}"
        else: # System or other roles
            panel_role_display_text = f"[{message.role}]{message.role.capitalize()}[/{message.role}]"
            # current_border_style remains as message.role (e.g. yellow for system)
            # model_info remains empty

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

        # Add MCP server/tool info if available (for assistant messages that used tools)
        # This is for the *body* of the panel, not the title.
        if message.role == "assistant" and (message.server or message.tool) and not (message.tool == model_info.split(" @ ")[0].strip()):
            # The 'and not (message.tool == model_info...)' is to avoid duplicating tool info if it's already in title
            # However, model_info in title is for assistant's *own* model, not necessarily the tool it just ran.
            # This part is about showing details of a tool the assistant *just used in its response content*.
            mcp_info_str = "```\n"
            if message.server:
                mcp_info_str += f"Server: {message.server}\n"
            if message.tool:
                mcp_info_str += f"Tool: {message.tool}\n"
            if message.arguments:
                import json # Keep import here for clarity of this block's dependency
                mcp_info_str += f"Arguments: {json.dumps(message.arguments, indent=2, ensure_ascii=False)}\n"
            mcp_info_str += "```\n"
            display_content += f"\n{mcp_info_str}"

        # If the panel would be blue (tool/process info), or the title contains tool/server info, skip printing it entirely
        if current_border_style == "tool" or "[tool]Tool[/tool]" in panel_role_display_text or (model_info and "@" in model_info):
            return

        self.console.print(Panel(
            Markdown(display_content),
            title=f"{index_str}{panel_role_display_text} {timestamp}{model_info}",
            border_style=current_border_style,
            padding=0
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

        # Buffer for tool call handling
        buffer = ""
        in_tool_call = False

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

            # Process reasoning content first
            if chunk_reasoning is not None: # Process if not None
                if not is_reasoning_block:
                    is_reasoning_block = True
                    if self.show_reasoning:
                        new_display_chunk += "> reasoning\n"
                if self.show_reasoning:
                    new_display_chunk += chunk_reasoning
                collected_reasoning_content.append(chunk_reasoning) # Collect all non-None reasoning

            if is_reasoning_block and chunk_reasoning is None and chunk_content is not None: # End of reasoning
                if self.show_reasoning:
                    new_display_chunk += "\n> summary\n"
                is_reasoning_block = False

            # Process main content with tool call filtering
            if chunk_content is not None:
                # Add to full content collection for later use
                collected_content.append(chunk_content)
                
                # Handle tool call filtering in streaming
                buffer += chunk_content
                
                # Check for opening tag
                if not in_tool_call and "<use_mcp_tool>" in buffer:
                    # Extract and add text before the tool call
                    start_idx = buffer.find("<use_mcp_tool>")
                    if start_idx > 0:
                        new_display_chunk += buffer[:start_idx]
                    
                    # Update buffer to keep only the part from the tag onwards
                    buffer = buffer[start_idx:]
                    in_tool_call = True
                
                # Check for closing tag if already in a tool call
                elif in_tool_call and "</use_mcp_tool>" in buffer:
                    # Found the end of the tool call
                    end_idx = buffer.find("</use_mcp_tool>") + len("</use_mcp_tool>")
                    
                    # Discard the tool call part
                    in_tool_call = False
                    
                    # Keep text after the tool call
                    if end_idx < len(buffer):
                        new_display_chunk += buffer[end_idx:]
                    
                    # Reset buffer
                    buffer = ""
                
                # If not in tool call, add content directly
                elif not in_tool_call:
                    new_display_chunk += chunk_content
                
                # If in tool call, just accumulate in buffer but don't display

            # Add to stream buffer if there's anything to display
            if new_display_chunk: 
                stream_buffer.add_content(new_display_chunk)
        
        # After streaming is complete
        # If we're still inside a tool call at the end, we should discard that partial content
        # Text already displayed is fine, just don't display any incomplete tool call
        
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
        """
        Stream and display the response in real-time using Rich Live.
        The Live display will be updated with the accumulated content.
        A single, final, fully rendered Markdown message is printed after the stream.
        """
        stream_buffer = StreamBuffer(max_chars_per_second=self.max_chars_per_second)
        
        # This string will hold the full content for the Rich Live display, 
        # potentially including reasoning markers if self.show_reasoning is true.
        accumulated_markdown_for_live_display = ""

        # _collect_stream_content will feed the stream_buffer.
        # It returns (display_ready_text, raw_reasoning_text, provider, model)
        # where display_ready_text is the first element.
        collection_task = asyncio.create_task(
            self._collect_stream_content(response_stream, stream_buffer)
        )

        has_started_printing_content = False
        if model_name_for_status:
            status_text = f"[bold green]{model_name_for_status}[/bold green]"
        else:
            status_text = f"[bold green]Thinking...[/bold green]"
        current_live_update_object = Status(status_text.strip(), spinner="dots", console=self.console)

        # Live is NOT transient. Its last state will persist.
        with Live(console=self.console, refresh_per_second=10, auto_refresh=True) as live:
            live.update(current_live_update_object)

            while True:
                # Check if collection is done AND stream_buffer is empty.
                if collection_task.done() and not stream_buffer.has_remaining:
                    break 

                chunk_from_buffer = stream_buffer.get_next_chunk()

                if chunk_from_buffer:
                    if not has_started_printing_content:
                        accumulated_markdown_for_live_display = chunk_from_buffer
                        has_started_printing_content = True
                    else:
                        accumulated_markdown_for_live_display += chunk_from_buffer
                    
                    current_live_update_object = Markdown(accumulated_markdown_for_live_display)
                    live.update(current_live_update_object)
                
                # Yield control if no chunk, allowing collection_task to run or loop to re-check.
                elif not collection_task.done():
                    await asyncio.sleep(0.05) 
                elif collection_task.done() and stream_buffer.has_remaining: # Collection done, but buffer still has content
                    await asyncio.sleep(0.01) # Process buffer quickly
                # No explicit else with sleep needed here, as the main loop condition will eventually be met.

            # After the loop, collection_task is done and stream_buffer is empty.
            # If no content was ever streamed, update Live to show "No response".
            if not has_started_printing_content:
                live.update(Markdown("🤔 No response or empty response received."))
            # Otherwise, Live's last state is already the full accumulated_markdown_for_live_display.

        # --- Live context has ended. Its display will persist. ---
        logger.debug("Live display loop ended.")

        final_display_string, raw_reasoning_string, provider, model = await collection_task
        
        # NO EXPLICIT PRINT HERE. Live object handles the final display.
        # logger.debug(f"Final display string (from collection): {final_display_string}") # Keep for debugging if needed

        # Logic to determine actual_summary_text to return to ChatManager
        # This text should be the core assistant message, without our display markers like "> reasoning"
        actual_summary_text = final_display_string 
        if self.show_reasoning:
            # If reasoning was shown, final_display_string contains it along with markers.
            # We need to extract the summary part that followed "> summary\n"
            # or what was intended as summary if markers are missing.
            summary_marker = "\n> summary\n"
            reasoning_marker = "> reasoning\n"
            
            if summary_marker in final_display_string:
                # Summary is everything after the last occurrence of summary_marker
                actual_summary_text = final_display_string.rsplit(summary_marker, 1)[-1]
            elif final_display_string.startswith(reasoning_marker):
                # It started with reasoning, but no explicit summary marker.
                # The raw_reasoning_string is the key here.
                # The displayed reasoning might be `reasoning_marker + raw_reasoning_string`.
                # Anything after that in final_display_string is the summary.
                
                # Construct what the displayed reasoning part would look like
                displayed_reasoning_part = reasoning_marker + raw_reasoning_string
                
                if final_display_string.startswith(displayed_reasoning_part):
                    actual_summary_text = final_display_string[len(displayed_reasoning_part):].strip()
                elif final_display_string.strip() == reasoning_marker.strip() or \
                     (raw_reasoning_string and final_display_string.strip() == (reasoning_marker + raw_reasoning_string).strip()):
                    # Only reasoning marker was displayed, or reasoning marker + raw_reasoning was the entire display
                    actual_summary_text = "" 
                else:
                    # Fallback: if it starts with reasoning_marker, but doesn't match raw_reasoning_string structure,
                    # assume the content after reasoning_marker is the summary. This is less precise.
                    actual_summary_text = final_display_string[len(reasoning_marker):].strip()
            # If no reasoning_marker and no summary_marker, actual_summary_text remains final_display_string
            # This means self.show_reasoning was true, but _collect_stream_content didn't add markers.

        # If after all this, actual_summary_text is empty but raw_reasoning_string is not,
        # it means the LLM might have only provided reasoning.
        # ChatManager should receive the raw_reasoning_string correctly.
        # actual_summary_text being empty in this case is correct.

        return actual_summary_text, raw_reasoning_string, provider, model

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
            border_style="yellow",
            padding=0
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
                    border_style="yellow",
                    padding=0
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
            border_style="red",
            padding=0
        ))

    def clear_lines(self, lines: int):
        """Clear the specified number of lines using ANSI escape sequences

        Args:
            lines: Number of lines to clear
        """
        for _ in range(lines):
            sys.stdout.write("\033[F")   # Cursor up one line
