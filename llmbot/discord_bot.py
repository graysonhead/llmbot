"""Discord bot integration for llmbot."""

import logging
import os
import re

import discord  # type: ignore[import-not-found]
from discord.ext import commands  # type: ignore[import-not-found]
from openwebui_chat_client import (  # type: ignore[import-not-found,import-untyped]
    OpenWebUIClient,
)

# Set up logging
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)


class LLMBot(commands.Bot):
    """Discord bot that forwards messages to OpenWebUI backend."""

    def __init__(
        self,
        server_url: str,
        model: str = "llama3.1:8b",
        request_timeout: float = 15.0,
        system_message: str | None = None,
    ) -> None:
        """Initialize the bot with OpenWebUI connection."""
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

        self.server_url = server_url
        self.model = model
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

        self.openwebui_client = OpenWebUIClient(
            base_url=server_url, token=self.api_key, default_model_id=self.model
        )

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
            "Query received - User: %s, Model: %s, Query: %s",
            user_name,
            model_to_use,
            cleaned_query,
        )

        # Show typing indicator for the entire process
        async with message.channel.typing():
            try:
                # Format query with user name for identification
                formatted_query = f"{user_name}: {cleaned_query}"

                # Use openwebui-chat-client
                result = self.openwebui_client.chat(
                    question=formatted_query,
                    model_id=model_to_use,
                    chat_title=f"discord-channel-{channel_id}",
                )

                response_text = result.get("response") if result else None
                if not response_text:
                    response_text = "No response received from the model."

                logger.info(
                    "Query successful - User: %s, Response: %d chars",
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
                    "Query failed - User: %s",
                    user_name,
                )
                await message.reply(error_msg)


async def start_discord_bot(
    token: str,
    server_url: str,
    *,
    model: str = "llama3.1:8b",
    request_timeout: float = 15.0,
    system_message: str | None = None,
) -> None:
    """Start the Discord bot."""
    bot = LLMBot(server_url, model, request_timeout, system_message)
    await bot.start(token)
