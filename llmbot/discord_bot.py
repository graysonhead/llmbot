"""Discord bot integration for llmbot."""

import logging
import os
import re
from collections import defaultdict, deque

import discord  # type: ignore[import-not-found]
from discord.ext import commands  # type: ignore[import-not-found]
from openai import OpenAI  # type: ignore[import-not-found]
from openai.types.chat import (
    ChatCompletionMessageParam,  # type: ignore[import-not-found]
)

# Set up logging
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)


class LLMBot(commands.Bot):
    """Discord bot that forwards messages to OpenWebUI backend with context."""

    def __init__(
        self,
        server_url: str,
        model: str = "llama3.1:8b",
        context_limit: int = 10,
        request_timeout: float = 15.0,
        system_message: str | None = None,
    ) -> None:
        """Initialize the bot with OpenWebUI connection."""
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

        self.server_url = server_url
        self.model = model
        self.context_limit = context_limit
        self.request_timeout = request_timeout
        self.api_key = os.getenv("OPENWEBUI_API_KEY")
        self.system_message = system_message or (
            "You are an AI assistant helping multiple users in a group conversation. "
            "Messages will be formatted as 'username: message content'. "
            "Try to differentiate between users by addressing them by name when "
            "appropriate and maintaining awareness of who said what in the "
            "conversation context. "
            "Example format: 'Alice: What's the weather like?' or "
            "'Bob: Thanks for the help!'"
        )

        if not self.api_key:
            msg = "OPENWEBUI_API_KEY environment variable not set"
            raise ValueError(msg)

        self.openai_client = OpenAI(
            base_url=server_url, api_key=self.api_key, timeout=self.request_timeout
        )

        # Store conversation history per channel
        # Each channel gets a deque with limited size to maintain context window
        self.channel_contexts: dict[int, deque[ChatCompletionMessageParam]] = (
            defaultdict(lambda: self._create_new_context())
        )

    def _create_new_context(self) -> deque[ChatCompletionMessageParam]:
        """Create a new context deque with system message pre-populated."""
        context: deque[ChatCompletionMessageParam] = deque(maxlen=self.context_limit)
        context.append({"role": "system", "content": self.system_message})
        return context

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

    async def on_ready(self) -> None:
        """Handle bot ready event."""
        # Bot is ready - could add logging here if needed

    async def on_message(self, message: discord.Message) -> None:
        """Handle incoming messages."""
        # Don't respond to bot's own messages
        if message.author == self.user:
            return

        # Check if bot is mentioned
        if self.user and self.user.mentioned_in(message):
            # Remove the mention from the message content
            content = message.content
            mention_pattern = rf"<@!?{self.user.id}>"
            content = re.sub(mention_pattern, "", content).strip()

            if content:
                await self.handle_llm_query(message, content)

        # Process commands
        await self.process_commands(message)

    async def handle_llm_query(self, message: discord.Message, query: str) -> None:
        """Handle LLM query and respond with channel context."""
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

        # Show typing indicator for the entire process
        async with message.channel.typing():
            try:
                # Add user message to context (use cleaned query)
                self.channel_contexts[channel_id].append(
                    {
                        "role": "user",
                        "content": f"{user_name}: {cleaned_query}",
                    }
                )

                # Build messages with context
                messages = list(self.channel_contexts[channel_id])

                response = self.openai_client.chat.completions.create(
                    model=model_to_use, messages=messages
                )

                response_text = response.choices[0].message.content
                if not response_text:
                    response_text = "No response received from the model."

                # Add bot response to context
                self.channel_contexts[channel_id].append(
                    {
                        "role": "assistant",
                        "content": response_text,
                    }
                )

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

    @commands.command(name="clear_context")  # type: ignore[type-var]
    async def clear_context(self, ctx: commands.Context) -> None:
        """Clear the conversation context for this channel."""
        channel_id = ctx.channel.id
        self.channel_contexts[channel_id] = self._create_new_context()
        await ctx.send("✅ Channel context cleared!")

    @commands.command(name="context_size")  # type: ignore[type-var]
    async def context_size(self, ctx: commands.Context) -> None:
        """Show current context size for this channel."""
        channel_id = ctx.channel.id
        size = len(self.channel_contexts[channel_id])
        await ctx.send(f"📊 Current context size: {size}/{self.context_limit} messages")


async def start_discord_bot(  # noqa: PLR0913
    token: str,
    server_url: str,
    *,
    model: str = "llama3.1:8b",
    context_limit: int = 10,
    request_timeout: float = 15.0,
    system_message: str | None = None,
) -> None:
    """Start the Discord bot."""
    bot = LLMBot(server_url, model, context_limit, request_timeout, system_message)
    await bot.start(token)
