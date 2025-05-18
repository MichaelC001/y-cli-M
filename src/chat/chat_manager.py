from typing import List, Dict, Optional
from contextlib import AsyncExitStack
from types import SimpleNamespace

from chat.models import Chat, Message
from .repository import ChatRepository
from .service import ChatService
from cli.display_manager import DisplayManager
from cli.input_manager import InputManager
from mcp_server.mcp_manager import MCPManager
from prompt.preset import time_prompt
from util import generate_id
from .utils.tool_utils import contains_tool_use, split_content
from .utils.message_utils import create_message
from .provider.base_provider import BaseProvider
from bot import BotConfig
from config import prompt_service, mcp_service
from config import config
from loguru import logger

class ChatManager:
    def __init__(
        self,
        repository: ChatRepository,
        display_manager: DisplayManager,
        input_manager: InputManager,
        mcp_manager: MCPManager,
        provider: BaseProvider,
        bot_config: BotConfig,
        chat_id: Optional[str] = None,
        verbose: bool = False
    ):
        """Initialize chat manager with required components.

        Args:
            repository: Repository for chat persistence
            display_manager: Manager for display and UI
            input_manager: Manager for user input
            mcp_manager: Manager for MCP operations
            provider: Chat provider for interactions
            bot_config: Bot configuration
            chat_id: Optional ID of existing chat to load
            verbose: Whether to show verbose output
        """
        self.service = ChatService(repository)
        self.bot_config = bot_config
        self.model = bot_config.model
        self.display_manager = display_manager
        self.input_manager = input_manager
        self.mcp_manager = mcp_manager
        self.provider = provider
        self.verbose = verbose

        # Set up cross-manager references
        self.provider.set_display_manager(display_manager)

        # Initialize chat state
        self.current_chat: Optional[Chat] = None
        self.external_id: Optional[str] = None
        self.messages: List[Message] = []
        self.system_prompt: Optional[str] = None
        self.chat_id: Optional[str] = None
        self.continue_exist = False
        self.last_printed_text_output: Optional[str] = None # Track last text output

        if chat_id:
            self.chat_id = chat_id
            self.continue_exist = True # Assume we intend to continue if an ID is given
        else:
            self.chat_id = generate_id()
            self.continue_exist = False # Clearly a new chat if no ID was given

    async def _load_chat(self, chat_id: str) -> bool: # Return bool
        """Load an existing chat by ID. Returns True if successful, False otherwise."""
        existing_chat = await self.service.get_chat(chat_id)
        if not existing_chat:
            # self.display_manager.print_error(f"Chat {chat_id} not found") # Optionally print, or let caller decide
            return False # Chat not found

        self.messages = existing_chat.messages
        self.current_chat = existing_chat
        self.external_id = existing_chat.external_id # Also load external_id

        if self.verbose:
            logger.info(f"Loaded {len(self.messages)} messages from chat {chat_id}")
        return True # Chat loaded successfully

    def get_user_confirmation(self, content: str, server_name: str = None, tool_name: str = None) -> bool:
        """Get user confirmation before executing tool use

        Args:
            content: The tool use content (currently unused in prompt after this change)
            server_name: The MCP server name
            tool_name: The tool name being executed

        Returns:
            bool: True if confirmed, False otherwise
        """
        # Check if auto_confirm is enabled for this tool
        if server_name and tool_name and self.bot_config.mcp_servers:
            server_config = mcp_service.get_config(server_name)
            if server_config and hasattr(server_config, 'auto_confirm') and tool_name in server_config.auto_confirm:
                if self.verbose:
                    logger.info(f"Auto-confirming tool use for {server_name}/{tool_name}")
                return True

        prompt_message = f"Tool use confirm [{server_name}/{tool_name}] (y/n): "
        if not server_name and not tool_name:
            prompt_message = "Tool use confirm (y/n): " 
        
        self.display_manager.console.print() # Add a newline for spacing
        while True:
            # Use standard input() for simple y/n confirmation
            response = input(prompt_message).strip().lower()
            if response in ['y', 'yes']:
                return True
            elif response in ['n', 'no']:
                return False
            # If response is invalid, print error message directly using console
            self.display_manager.console.print("[yellow]Please answer 'y' or 'n'[/yellow]")

    async def process_user_message(self, user_message: Message):
        self.messages.append(user_message)
        self.display_manager.display_message_panel(user_message, index=len(self.messages) - 1)
        # Store user message content as last output
        if isinstance(user_message.content, str):
            self.last_printed_text_output = user_message.content
        elif isinstance(user_message.content, list):
            self.last_printed_text_output = next((part.get('text') for part in user_message.content if part.get('type') == 'text'), None)

        stream_generator = None
        external_id = None
        assistant_message_content_full = ""
        assistant_reasoning_content_full = ""
        provider_name_from_stream = self.bot_config.name # Default
        model_name_from_stream = self.bot_config.model # Default

        try:
            # Step 1: Get the stream generator from the provider (makes the API call)
            # This spinner covers the initial request to the provider.
            with self.display_manager.console.status("[bold green]Requesting response...", spinner="dots"):
                stream_generator, external_id = await self.provider.call_chat_completions(
                    self.messages, self.current_chat, self.system_prompt
                )

            # Step 2: Stream the response using DisplayManager.
            # DisplayManager will show its own "Thinking..." until first content arrives.
            if stream_generator:
                # stream_response now returns provider and model info as well
                assistant_message_content_full, assistant_reasoning_content_full, \
                    provider_from_display, model_from_display = await self.display_manager.stream_response(
                        stream_generator, 
                        model_name_for_status=self.bot_config.model # Pass the model name here
                    )
                
                if provider_from_display:
                    provider_name_from_stream = provider_from_display
                # Use model_from_display if available, otherwise stick with bot_config.model if it was used for status
                model_name_from_stream = model_from_display if model_from_display else self.bot_config.model
            else:
                assistant_message_content_full = "Error: Could not retrieve response stream from provider."
                # No stream to display, so no provider/model info from stream.

        except Exception as e:
            logger.error(f"Error during chat completion or streaming: {e}")
            self.display_manager.console.print(f"[red]Error: {e}[/red]")
            assistant_message_content_full = f"An error occurred: {str(e)}"

        if external_id:
            self.external_id = external_id
        
        # Step 3: Create and process the assistant message
        assistant_message = create_message(
            "assistant",
            assistant_message_content_full,
            reasoning_content=assistant_reasoning_content_full if assistant_reasoning_content_full else None,
            provider=provider_name_from_stream, 
            model=model_name_from_stream, 
            reasoning_effort=self.bot_config.reasoning_effort if self.bot_config.reasoning_effort else None
        )
        assistant_message.already_displayed_live = True 
        
        await self.process_assistant_message(assistant_message)
        await self.persist_chat()

    async def process_assistant_message(self, assistant_message: Message):
        """Process assistant response and handle tool use recursively"""
        # Extract content and metadata based on response type
        content = assistant_message.content

        if not contains_tool_use(content):
            self.messages.append(assistant_message)
            self.display_manager.display_message_panel(assistant_message, index=len(self.messages) - 1)
            # Store assistant message content as last output
            if isinstance(content, str):
                self.last_printed_text_output = content
            elif isinstance(content, list):
                self.last_printed_text_output = next((part.get('text') for part in content if part.get('type') == 'text'), None)
            return

        # Handle response with tool use
        plain_content, tool_content = split_content(content)

        # Extract MCP tool info before updating content
        mcp_tool = self.mcp_manager.extract_mcp_tool_use(tool_content)
        if not mcp_tool:
            return
        server_name, tool_name, arguments = mcp_tool
        # Add server, tool, and arguments info to assistant message
        assistant_message.server = server_name
        assistant_message.tool = tool_name
        assistant_message.arguments = arguments

        # Update last assistant message with plain content
        assistant_message.content = plain_content
        self.messages.append(assistant_message)
        self.display_manager.display_message_panel(assistant_message, index=len(self.messages) - 1)
        if isinstance(plain_content, str):
             self.last_printed_text_output = plain_content
        elif isinstance(plain_content, list):
             self.last_printed_text_output = next((part.get('text') for part in plain_content if part.get('type') == 'text'), None)

        # Get user confirmation for tool execution
        if not self.get_user_confirmation(tool_content, server_name, tool_name):
            no_exec_msg = "Tool execution cancelled by user."
            self.display_manager.console.print(f"\n[yellow]{no_exec_msg}[/yellow]")
            user_message = create_message("user", no_exec_msg)
            self.messages.append(user_message)
            return

        # Execute tool and get results
        tool_results = await self.mcp_manager.execute_tool(server_name, tool_name, arguments)

        # Create user message with tool results and include tool info
        user_message = create_message("user", tool_results, server=server_name, tool=tool_name, arguments=arguments)

        # Process user message and assistant response recursively
        await self.process_user_message(user_message)

    async def persist_chat(self):
        """Persist current chat state"""
        if not self.current_chat:
            # Create new chat with pre-generated ID
            self.current_chat = await self.service.create_chat(self.messages, self.external_id, self.chat_id)
        else:
            # Update existing chat - external_id will be preserved automatically
            self.current_chat = await self.service.update_chat(self.current_chat.id, self.messages, self.external_id)

    async def run(self):
        """Run the chat session"""
        async with AsyncExitStack() as exit_stack:
            try:
                if self.verbose:
                    logger.info(f"Chat manager run. Chat ID: {self.chat_id}, Continue: {self.continue_exist}")
                
                storage_type = config.get('storage_type', 'file')
                if storage_type == 'cloudflare':
                    await self.service.repository._sync_from_r2_if_needed()
                
                if self.continue_exist: # If an ID was provided, try to load it
                    loaded_successfully = await self._load_chat(self.chat_id)
                    if not loaded_successfully:
                        if self.verbose:
                            logger.info(f"Chat ID {self.chat_id} provided but not found in storage. Starting as a new chat.")
                        self.continue_exist = False # It's actually a new chat
                        self.messages = [] # Ensure messages are empty for a new chat
                        self.current_chat = None # Ensure current_chat is None
                        self.external_id = None # Ensure external_id is None
                
                if self.verbose and self.continue_exist:
                    logger.info(f"Continuing chat {self.chat_id} with {len(self.messages)} messages.")
                elif self.verbose: # This will now also catch new chats where an ID was generated or provided but not found
                    logger.info(f"Starting new chat {self.chat_id}.")

                # Init basic system prompt
                self.system_prompt = time_prompt + "\n"

                # Initialize MCP and system prompt if MCP server settings exist
                if self.bot_config.mcp_servers:
                    # Connect and get status lists
                    connected_servers, unconnected_servers = await self.mcp_manager.connect_to_servers(self.bot_config.mcp_servers)

                    # Print status summary based on daemon connection and server lists
                    if self.mcp_manager.connected_to_daemon:
                        if connected_servers:
                            self.display_manager.console.print(f"[green]mcp connected:[/green] {', '.join(connected_servers)}")
                        if unconnected_servers:
                             self.display_manager.console.print(f"[yellow]mcp not connected:[/yellow] {', '.join(unconnected_servers)}")
                             self.display_manager.console.print("[yellow](Check MCP daemon status or config)[/yellow]")
                        elif not connected_servers: # Daemon connected but no configured servers found
                             self.display_manager.console.print("[yellow]mcp: Daemon connected, but no configured servers found active.[/yellow]")
                    else:
                         self.display_manager.console.print("[yellow]mcp: Daemon not running or connection failed.[/yellow]")

                    # Get prompt info (this part remains the same)
                    mcp_system_prompt = await self.mcp_manager.get_mcp_prompt(self.bot_config.mcp_servers, prompt_service)
                    if mcp_system_prompt:
                        self.system_prompt += mcp_system_prompt + "\n"

                # Add additional prompts to system prompt
                if self.bot_config.prompts:
                    for prompt in self.bot_config.prompts:
                        if prompt not in ["mcp"]:
                            prompt_config = prompt_service.get_prompt(prompt)
                            if prompt_config:
                                self.system_prompt += prompt_config.content + "\n"

                if self.verbose:
                    self.display_manager.display_help()

                # Display existing messages if continuing from a previous chat
                if self.messages:
                    self.display_manager.display_chat_history(self.messages)

                while True:
                    # Get user input, multi-line flag, and line count
                    # user_input, is_multi_line, line_count = self.input_manager.get_input()
                    input_type, value = self.input_manager.get_input()

                    # Check for exit type returned directly by get_input
                    if input_type == 'exit':
                        self.display_manager.console.print("\n[yellow]Goodbye![/yellow]")
                        break

                    if input_type == 'empty':
                    # if not user_input:
                        self.display_manager.console.print("[yellow]Please enter a message or command.[/yellow]")
                        continue

                    # Handle commands
                    if input_type == 'command':
                        if value == '/copy':
                            # Pass the last printed output to the handler
                            self.input_manager.handle_copy_command(value, self.messages, self.last_printed_text_output)
                        elif value == '/translate':
                            content_to_translate = self.input_manager.handle_translate_command(value, self.messages)
                            if content_to_translate:
                                # Clear the '/translate' input line
                                self.display_manager.clear_lines(1)
                                # Call the provider's translate method
                                self.display_manager.console.print("[dim]Translating...[/dim]")
                                translated_text = await self.provider.translate_text(content_to_translate, target_language="Chinese")
                                if translated_text:
                                    self.display_manager.console.print(f"[blue]Translation:[/blue]\n{translated_text}")
                                    self.last_printed_text_output = translated_text # Store translation as last output
                                else:
                                    self.display_manager.console.print("[yellow]Translation failed. See console for details.[/yellow]")
                            # If content_to_translate is None, input_manager already printed an error
                        elif value == '/save':
                            # Pass the last printed output if save needs it
                            self.input_manager.handle_save_command(value, self.messages)
                        # Add other command handlers here if needed
                        continue # Go back to prompt after handling command

                    # Handle legacy copy command (optional, could be removed if /copy is preferred)
                    if value.lower().startswith('copy '):
                         # Pass the last printed output here too if needed, though legacy uses index
                        if self.input_manager.handle_copy_command(value, self.messages, self.last_printed_text_output):
                            continue

                    # Process as regular chat input
                    if input_type == 'chat':
                        user_input = value
                        # Add user message to history
                        user_message = create_message("user", user_input)
                        # if is_multi_line:
                        #     # clear <<EOF line and EOF line
                        #     self.display_manager.clear_lines(2)

                        # Estimate lines cleared (this might need adjustment based on prompt toolkit rendering)
                        # For simplicity, assume single line for now, multi-line needs more robust handling
                        self.display_manager.clear_lines(1) # Clear the input line

                        await self.process_user_message(user_message)

            except (KeyboardInterrupt, EOFError):
                self.display_manager.console.print("\n[yellow]Chat interrupted. Exiting...[/yellow]")
            finally:
                # Clear sessions on exit
                self.mcp_manager.clear_sessions()
