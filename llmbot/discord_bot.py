"""Discord bot integration for llmbot."""

import logging
import re

import discord  # type: ignore[import-not-found]
import ollama  # type: ignore[import-not-found]
from discord.ext import commands  # type: ignore[import-not-found]

from .tools import chat_with_tools, set_tool_config

# Set up logging
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)


class LLMBot(commands.Bot):
    """Discord bot that forwards messages to Ollama backend."""

    def __init__(  # noqa: PLR0913
        self,
        ollama_host: str = "http://localhost:11434",
        model: str = "llama3.1:8b",
        searxng_url: str = "http://localhost:8080/search",
        request_timeout: float = 15.0,
        system_message: str | None = None,
        additional_system_message: str | None = None,
        context_length: int = 2048,
        context_trim_threshold: float = 0.8,
        *,
        enable_mcp_tools: bool = True,
    ) -> None:
        """Initialize the bot with Ollama connection."""
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

        self.ollama_host = ollama_host
        self.model = model
        self.request_timeout = request_timeout
        self.context_length = context_length
        self.context_trim_threshold = context_trim_threshold
        self.enable_mcp_tools = enable_mcp_tools

        # Configure tools with searxng URL
        set_tool_config(searxng_url)

        # Build system message
        base_system_message = system_message or (
            "You are an AI assistant helping multiple users in a group conversation. "
            "Messages will be formatted as 'username: message content'. "
            "Try to differentiate between users by addressing them by name when "
            "appropriate and maintaining awareness of who said what in the "
            "conversation context. "
            "Example format: 'Alice: What's the weather like?' or "
            "'I said: The weather looks sunny today!' "
            "You have access to tools that can provide real-time information. "
            "When you use a tool, you will receive the result and should provide "
            "that information to the user along with any relevant explanation. "
            "Always trust and use the results from tools when they are available. "
            "When using the get_metar tool, always display the full raw METAR "
            "between backtick characters (`) for easy reading, then put your "
            "description below. Please include a description for all non-null "
            "attributes. CRITICAL: always mention that this information should "
            "not be used for real-life flight planning purposes. "
            "When using tools for mathematical operations (like counting letters "
            "or adding numbers), repeat the exact result from the tool verbatim "
            "to ensure accuracy."
            "When asked to search for things on the web, always search for "
            "multiple sources, and provide links to any sources you site."
        )

        # Append additional system message if provided
        if additional_system_message:
            self.system_message = (
                f"{base_system_message}\n\n{additional_system_message}"
            )
        else:
            self.system_message = base_system_message

        self.ollama_client = ollama.Client(host=ollama_host)

        # Per-channel conversation history: channel_id -> list of message dicts
        self.conversation_history: dict[int, list[dict[str, str]]] = {}

    def _parse_model_from_query(self, query: str) -> tuple[str, str]:
        """Parse model specification from query and return (model, cleaned_query)."""
        # Look for !model=<model_name> pattern
        model_pattern = r"!model=(\S+)"
        match = re.search(model_pattern, query)

        if match:
            model_name = match.group(1)
            # Remove the model specification from the query
            cleaned_query = re.sub(model_pattern, "", query).strip()
            return model_name, cleaned_query

        # No model specified, use default
        return self.model, query

    def _estimate_tokens(self, text: str) -> int:
        """Rough token estimation (4 chars ≈ 1 token for English)."""
        return len(text) // 4

    def _format_message_with_timestamp(
        self, user_name: str, content: str, *, is_bot: bool = False
    ) -> str:
        """Format a message with user identification."""
        if is_bot:
            return f"I said: {content}"
        return f"{user_name}: {content}"

    def _add_to_history(
        self, channel_id: int, user_name: str, content: str, *, is_bot: bool = False
    ) -> None:
        """Add a message to the channel's conversation history."""
        if channel_id not in self.conversation_history:
            self.conversation_history[channel_id] = []

        formatted_message = self._format_message_with_timestamp(
            user_name, content, is_bot=is_bot
        )
        message_dict = {
            "role": "assistant" if is_bot else "user",
            "content": formatted_message,
        }

        self.conversation_history[channel_id].append(message_dict)

    def _trim_history_if_needed(self, channel_id: int) -> None:
        """Remove oldest messages if we're approaching context limit."""
        if channel_id not in self.conversation_history:
            return

        history = self.conversation_history[channel_id]

        # Calculate current token usage (system message + history)
        system_tokens = self._estimate_tokens(self.system_message)
        history_tokens = sum(self._estimate_tokens(msg["content"]) for msg in history)
        total_tokens = system_tokens + history_tokens

        # Use configurable threshold to leave room for response
        token_threshold = int(self.context_length * self.context_trim_threshold)

        # Remove oldest messages until we're under threshold
        while total_tokens > token_threshold and len(history) > 1:
            removed_msg = history.pop(0)
            total_tokens -= self._estimate_tokens(removed_msg["content"])
            logger.info(
                "Trimmed oldest message from channel %s context (%d -> %d tokens)",
                channel_id,
                total_tokens + self._estimate_tokens(removed_msg["content"]),
                total_tokens,
            )

    async def verify_context_length(self, model_name: str) -> None:
        """Verify the context length can be set for a model. Fails fast on errors."""
        try:
            # Make a test call to ensure the model accepts our context length
            self.ollama_client.chat(
                model=model_name,
                messages=[{"role": "user", "content": "test"}],
                options={"num_ctx": self.context_length},
            )

            # If we get here, the context length was accepted
            logger.info(
                "Context length %d verified for model %s",
                self.context_length,
                model_name,
            )

        except Exception as e:
            logger.exception(
                "Failed to set context length %d for model %s",
                self.context_length,
                model_name,
            )
            msg = (
                f"Cannot configure context length {self.context_length} "
                f"for model {model_name}: {e}"
            )
            raise RuntimeError(msg) from e

    async def on_ready(self) -> None:
        """Handle bot ready event."""
        # Bot is ready - could add logging here if needed

    async def on_message(self, message: discord.Message) -> None:
        """Handle incoming messages."""
        # Don't respond to bot's own messages
        if message.author == self.user:
            return

        # Check if this is a DM with exactly one other user
        is_dm = isinstance(message.channel, discord.DMChannel)

        if is_dm:
            # In DMs, respond to any message (no mention required)
            content = message.content.strip()
            if content:
                await self.handle_llm_query(message, content)
        elif self.user and self.user.mentioned_in(message):
            # In group channels/servers, only respond when mentioned
            # Remove the mention from the message content
            content = message.content
            mention_pattern = rf"<@!?{self.user.id}>"
            content = re.sub(mention_pattern, "", content).strip()

            if content:
                await self.handle_llm_query(message, content)

        # Process commands
        await self.process_commands(message)

    async def handle_llm_query(self, message: discord.Message, query: str) -> None:
        """Handle LLM query and respond."""
        channel_id = message.channel.id
        user_name = message.author.display_name

        # Parse model specification from query
        model_to_use, cleaned_query = self._parse_model_from_query(query)

        logger.info(
            "Query received - Channel: %s, User: %s, Model: %s, Query: %s",
            channel_id,
            user_name,
            model_to_use,
            cleaned_query,
        )

        # Add user message to history and trim if needed
        self._add_to_history(channel_id, user_name, cleaned_query, is_bot=False)
        self._trim_history_if_needed(channel_id)

        # Show typing indicator for the entire process
        async with message.channel.typing():
            try:
                # Build message list with system message + conversation history
                messages = [{"role": "system", "content": self.system_message}]

                # Add conversation history for this channel
                if channel_id in self.conversation_history:
                    messages.extend(self.conversation_history[channel_id])

                # Use ollama client with or without tools
                if self.enable_mcp_tools:
                    response_text, full_conversation = chat_with_tools(
                        messages,
                        self.ollama_client,
                        model_to_use,
                        options={"num_ctx": self.context_length},
                    )
                    # If tools were used, the conversation includes tool interactions
                    # Only add the final assistant response, not the tool calls
                    if len(full_conversation) > len(messages):
                        # Tools were used, add only the final response
                        # without "I said:" prefix
                        # Find the last assistant message in the conversation
                        for msg in reversed(full_conversation):
                            if (
                                msg.get("role") == "assistant"
                                and "content" in msg
                                and msg["content"]
                            ):
                                # Add this as a regular assistant message
                                # to maintain conversation flow
                                message_dict = {
                                    "role": "assistant",
                                    "content": f"Assistant: {response_text}",
                                }
                                self.conversation_history[channel_id].append(
                                    message_dict
                                )
                                break
                    else:
                        # No tools used, add normally
                        self._add_to_history(
                            channel_id, "Assistant", response_text, is_bot=True
                        )
                else:
                    result = self.ollama_client.chat(
                        model=model_to_use,
                        messages=messages,
                        options={"num_ctx": self.context_length},
                    )
                    response_text = (
                        result["message"]["content"]
                        if result
                        else "No response received"
                    )
                    # Add bot response to conversation history
                    self._add_to_history(
                        channel_id, "Assistant", response_text, is_bot=True
                    )

                if not response_text:
                    response_text = "No response received from the model."

                logger.info(
                    "Query successful - Channel: %s, User: %s, Response: %d chars",
                    channel_id,
                    user_name,
                    len(response_text),
                )

                # Discord has a 2000 character limit for messages
                discord_msg_limit = 2000
                if len(response_text) > discord_msg_limit:
                    # Split into multiple messages if too long
                    chunks = [
                        response_text[i : i + discord_msg_limit]
                        for i in range(0, len(response_text), discord_msg_limit)
                    ]
                    for chunk in chunks:
                        await message.reply(chunk)
                else:
                    await message.reply(response_text)

            except Exception as e:
                error_msg = f"Error processing your request: {e}"
                logger.exception(
                    "Query failed - Channel: %s, User: %s",
                    channel_id,
                    user_name,
                )
                await message.reply(error_msg)


async def start_discord_bot(  # noqa: PLR0913
    token: str,
    ollama_host: str = "http://localhost:11434",
    *,
    model: str = "llama3.1:8b",
    searxng_url: str = "http://localhost:8080/search",
    request_timeout: float = 15.0,
    system_message: str | None = None,
    additional_system_message: str | None = None,
    context_length: int = 2048,
    context_trim_threshold: float = 0.8,
    enable_mcp_tools: bool = True,
) -> None:
    """Start the Discord bot."""
    bot = LLMBot(
        ollama_host,
        model,
        searxng_url,
        request_timeout,
        system_message,
        additional_system_message,
        context_length,
        context_trim_threshold,
        enable_mcp_tools=enable_mcp_tools,
    )

    # Verify context length can be set before starting the bot
    try:
        await bot.verify_context_length(model)
    except RuntimeError as e:
        logger.exception("Bot startup failed")
        raise SystemExit(1) from e
    await bot.start(token)
