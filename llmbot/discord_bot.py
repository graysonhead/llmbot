"""Discord bot integration for llmbot."""

import asyncio
import logging
import re
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

_LOCAL_TZ = ZoneInfo("America/Chicago")


def _now_local_str() -> str:
    return datetime.now(_LOCAL_TZ).strftime("%A, %Y-%m-%d %H:%M %Z")
from typing import TYPE_CHECKING, Any

import discord  # type: ignore[import-not-found]
from discord.ext import commands  # type: ignore[import-not-found]

from .backends import OllamaBackend
from .loop_tools import (
    clear_current_loop,
    compute_next_run,
    set_current_loop,
    set_loop_tool_config,
)
from .memory import parse_consolidation_response
from .tools import LOOP_EXECUTION_TOOLS, chat_with_tools, set_tool_config

if TYPE_CHECKING:
    from .backends import LLMBackend
    from .memory import MemoryStore

# Set up logging
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)


class LLMBot(commands.Bot):
    """Discord bot that forwards messages to an LLM backend."""

    def __init__(  # noqa: PLR0913
        self,
        backend: "LLMBackend",
        searxng_url: str = "http://localhost:8080/search",
        request_timeout: float = 15.0,
        system_message: str | None = None,
        additional_system_message: str | None = None,
        context_length: int = 2048,
        context_trim_threshold: float = 0.8,
        *,
        enable_mcp_tools: bool = True,
        memory_store: "MemoryStore | None" = None,
        consolidation_threshold: float = 0.6,
        consolidation_keep_recent: int = 20,
        webui_url: str | None = None,
    ) -> None:
        """Initialize the bot with a configured LLM backend.

        Args:
            backend: LLM backend to use for all queries.
            searxng_url: SearXNG instance URL for web search tool.
            request_timeout: Timeout for HTTP requests in seconds.
            system_message: Override the default system prompt.
            additional_system_message: Append extra text to the system prompt.
            context_length: Token limit for conversation history trimming.
            context_trim_threshold: Fraction of context_length at which to trim.
            enable_mcp_tools: Whether to enable tool calling.
            memory_store: Optional SQLite-backed memory/summary store.
            consolidation_threshold: Fraction of context_length at which to consolidate history.
            consolidation_keep_recent: Raw messages to keep after consolidation.
            webui_url: Base URL of the web UI (e.g. http://localhost:8080) for tool call log links.
        """
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

        self.backend = backend
        self.request_timeout = request_timeout
        self.context_length = context_length
        self.context_trim_threshold = context_trim_threshold
        self.enable_mcp_tools = enable_mcp_tools
        self.memory_store = memory_store
        self.consolidation_threshold = consolidation_threshold
        self.consolidation_keep_recent = consolidation_keep_recent
        self.webui_url = webui_url
        # Tracks which channels have had their summary context loaded
        self._context_loaded: set[int] = set()
        # Tracks loop IDs currently executing to prevent concurrent re-runs
        self._running_loops: set[int] = set()
        # Maps channel_id -> {display_name: discord_user_id} for consolidation prompts
        self._channel_users: dict[int, dict[str, int]] = {}

        # Configure tools with searxng URL
        set_tool_config(searxng_url)

        # Give loop tools access to the Discord client and memory store
        if memory_store is not None:
            set_loop_tool_config(self, memory_store)

        # Build system message
        base_system_message = system_message or (
            "You are an AI assistant residing on the Head family's discord server. "
            "Messages will be formatted as 'username: message content'. "
            "Try to differentiate between users by addressing them by name when "
            "appropriate and maintaining awareness of who said what in the "
            "conversation context. "
            '"Darkside"\'s real name is Grayson Head, and "maeroselastic" is Maerose Head. '
            "They are husband and wife respectively, and have two children Wyatt and Owen. "
            "You have access to tools that can provide real-time information. "
            "When you use a tool, you will receive the result and should provide "
            "that information to the user along with any relevant explanation. "
            "Always trust and use the results from tools when they are available. "
            "When using the get_metar tool, always display the full raw METAR "
            "between backtick characters (`) for easy reading, then put your "
            "description below. Please include a description for all non-null "
            "attributes. "
            "When asked to search for things on the web, always search for "
            "multiple sources, and provide links to any sources you cite. "
            "If the user asks you to modify or delete a calendar entry, you may "
            "have to query for the events again to get the UID and modify or "
            "delete them. Always ask for confirmation before deleting something or "
            "modifying something if the request is not crystal clear. "
            "If the user doesn't specify a timezone when discussing calendar "
            "events assume CST/CDT as appropriate. The current date and time is provided "
            "in your system prompt — use it as your authoritative source and do not call "
            "a tool to look it up. Make sure you are adding future events in the current year unless "
            "otherwise specified. And always ask for clarification if it isn't exactly clear "
            "when things are supposed to be scheduled. "
            "IMPORTANT: You are incapable of creating, modifying, or deleting calendar entries or tasks without calling the appropriate tool. "
            "You MUST call the tool first. If you lack information needed to call the tool, ask the user — never claim an action was performed without a successful tool call."
        )

        # Append additional system message if provided
        if additional_system_message:
            self.system_message = (
                f"{base_system_message}\n\n{additional_system_message}"
            )
        else:
            self.system_message = base_system_message

        # Per-channel conversation history: channel_id -> list of message dicts
        self.conversation_history: dict[int, list[dict[str, str]]] = {}

    def _parse_model_from_query(self, query: str) -> tuple[str | None, str]:
        """Parse !model= override from query; return (model_or_None, cleaned_query).

        Returns None when no override is present so the backend uses its own model.
        """
        model_pattern = r"!model=(\S+)"
        match = re.search(model_pattern, query)

        if match:
            model_name = match.group(1)
            cleaned_query = re.sub(model_pattern, "", query).strip()
            return model_name, cleaned_query

        return None, query

    def _estimate_tokens(self, text: str) -> int:
        """Rough token estimation (4 chars ≈ 1 token for English)."""
        return len(text) // 4

    def _format_message_with_timestamp(
        self, user_name: str, content: str, *, is_bot: bool = False
    ) -> str:
        """Format a message with user identification."""
        if is_bot:
            return content
        return f"{user_name}: {content}"

    def _add_to_history(
        self,
        channel_id: int,
        user_name: str,
        content: str,
        *,
        is_bot: bool = False,
        user_id: int | None = None,
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

        # Track user IDs for consolidation prompts
        if not is_bot and user_id is not None:
            self._channel_users.setdefault(channel_id, {})[user_name] = user_id

    def _load_channel_context(self, channel_id: int) -> None:
        """Inject stored summary and raw messages into history on the first message."""
        if channel_id in self._context_loaded:
            return
        self._context_loaded.add(channel_id)

        if self.memory_store is None:
            return

        summary = self.memory_store.get_summary(channel_id)
        raw = self.memory_store.get_raw_history(channel_id)

        if not summary and not raw:
            return

        if channel_id not in self.conversation_history:
            self.conversation_history[channel_id] = []

        self.conversation_history[channel_id] = [
            *raw,
            *self.conversation_history[channel_id],
        ]
        logger.info(
            "Loaded context for channel %s: summary=%s, %d raw messages",
            channel_id,
            bool(summary),
            len(raw),
        )

    def _maybe_consolidate(self, channel_id: int) -> None:
        """Trigger memory consolidation when history exceeds the token threshold."""
        if self.memory_store is None:
            return
        self.memory_store.increment_message_count(channel_id)
        history = self.conversation_history.get(channel_id, [])
        history_tokens = sum(self._estimate_tokens(msg["content"]) for msg in history)
        token_threshold = int(self.context_length * self.consolidation_threshold)
        if history_tokens >= token_threshold:
            self._run_consolidation(channel_id)

    def _run_consolidation(self, channel_id: int) -> None:
        """Rewrite the channel summary and extract long-term memories from recent history."""
        if self.memory_store is None:
            return
        try:
            existing_summary = self.memory_store.get_summary(channel_id) or ""
            history = self.conversation_history.get(channel_id, [])

            user_map = self._channel_users.get(channel_id, {})
            user_map_text = (
                "User ID mapping: "
                + ", ".join(f"{name}={uid}" for name, uid in user_map.items())
                if user_map
                else ""
            )

            history_text = "\n".join(
                f"{msg['role']}: {msg['content']}" for msg in history
            )

            consolidation_prompt = (
                f"Current summary:\n{existing_summary or '(none)'}\n\n"
                + (f"{user_map_text}\n\n" if user_map_text else "")
                + f"Recent messages:\n{history_text}\n\n"
                "Review the above. Output a JSON object with exactly two keys:\n"
                '1. "summary": updated running summary — preserve important facts, '
                "decisions, ongoing tasks, and user preferences. Be concise.\n"
                '2. "memories": list of objects with keys user_id (int Discord snowflake), '
                "content (str), tags (list[str]), category "
                "(one of: fact, preference, task, note, workflow) — "
                "only include genuinely useful long-term facts.\n\n"
                "Output only the JSON object, no other text."
            )

            response = self.backend.api_chat(
                [{"role": "user", "content": consolidation_prompt}],
                "You are a memory consolidation assistant. Output only valid JSON.",
            )
            raw_text = self.backend.extract_text(response)
            parsed = parse_consolidation_response(raw_text)

            self.memory_store.save_summary(
                channel_id, existing_summary, parsed["summary"]
            )

            valid_memories = [
                m
                for m in parsed.get("memories", [])
                if isinstance(m.get("user_id"), int) and m.get("content")
            ]
            if valid_memories:
                self.memory_store.save_memories(valid_memories)

            # Keep only the most recent raw messages
            self.conversation_history[channel_id] = history[
                -self.consolidation_keep_recent :
            ]

            # Sync trimmed history back to DB
            self.memory_store.save_raw_history(
                channel_id, self.conversation_history[channel_id]
            )

            logger.info(
                "Consolidated memory for channel %s: %d memories saved, history trimmed to %d",
                channel_id,
                len(valid_memories),
                len(self.conversation_history[channel_id]),
            )
        except Exception:
            logger.exception("Memory consolidation failed for channel %s", channel_id)

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

    def _append_tool_log_link(
        self, channel_id: int, response_text: str, tool_log: list[dict[str, Any]]
    ) -> str:
        """Save tool call log and append a web UI link to the response if configured."""
        if tool_log and self.memory_store is not None and self.webui_url is not None:
            log_id = self.memory_store.save_tool_call_log(channel_id, tool_log)
            response_text += f"\n-# [tool calls]({self.webui_url}/tool-calls/{log_id})"
        return response_text

    async def on_ready(self) -> None:
        """Handle bot ready event."""
        asyncio.create_task(self._run_scheduler())  # noqa: RUF006
        logger.info("Loop scheduler started")

    async def _run_scheduler(self) -> None:
        """Background task: fire loops whose next_run has passed."""
        while True:
            await asyncio.sleep(1)
            if self.memory_store is None:
                continue
            now = datetime.now(UTC)
            for loop in self.memory_store.get_due_loops(now):
                if loop["id"] not in self._running_loops:
                    asyncio.create_task(self.execute_loop(loop))  # noqa: RUF006

    async def execute_loop(self, loop: dict) -> None:  # type: ignore[type-arg]
        """Run one loop iteration: call LLM, post to channel, update timestamps.

        Args:
            loop: A loop dict as returned by :meth:`MemoryStore.get_due_loops`.
        """
        loop_id: int = loop["id"]
        self._running_loops.add(loop_id)
        try:
            raw_channel = self.get_channel(loop["output_channel"])
            if raw_channel is None or not isinstance(
                raw_channel, discord.abc.Messageable
            ):
                logger.warning(
                    "Loop %d: channel %d not found or not messageable",
                    loop_id,
                    loop["output_channel"],
                )
                return
            channel: discord.abc.Messageable = raw_channel

            loop_system = f"{loop['prompt']}\n\nCurrent date and time (authoritative — trust this): {_now_local_str()}"

            def _run_loop() -> tuple[str, list[dict[str, Any]]]:
                set_current_loop(loop)
                try:
                    text, conv, _tl = chat_with_tools(
                        [{"role": "user", "content": "Run your scheduled task now."}],
                        self.backend,
                        loop_system,
                        model=loop["model"] or None,
                        tools=LOOP_EXECUTION_TOOLS,
                    )
                    return text, conv
                finally:
                    clear_current_loop()

            event_loop = asyncio.get_event_loop()
            response_text, _ = await event_loop.run_in_executor(None, _run_loop)

            stripped = response_text.strip()
            if not stripped or stripped.upper() == "SKIP":
                logger.info(
                    "Loop %d '%s': model returned %r — skipping post",
                    loop_id,
                    loop["name"],
                    stripped or "(empty)",
                )
            else:
                content = stripped
                if loop["target"]:
                    content = f"{loop['target']} {stripped}"

                discord_msg_limit = 2000
                if len(content) > discord_msg_limit:
                    chunks = [
                        content[i : i + discord_msg_limit]
                        for i in range(0, len(content), discord_msg_limit)
                    ]
                    for chunk in chunks:
                        await channel.send(chunk)
                else:
                    await channel.send(content)

            now = datetime.now(UTC)
            next_run = compute_next_run(
                loop["frequency"], after=now, timezone=loop["timezone"]
            )
            self.memory_store.update_loop_run(loop_id, now, next_run)  # type: ignore[union-attr]
            logger.info(
                "Loop %d '%s' executed; next_run=%s",
                loop_id,
                loop["name"],
                next_run.strftime("%Y-%m-%d %H:%M UTC"),
            )

        except Exception:
            logger.exception("Loop %d execution failed", loop_id)
        finally:
            self._running_loops.discard(loop_id)

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

        # Load prior summary context on first message for this channel
        if self.memory_store is not None:
            self._load_channel_context(channel_id)

        # Add user message to history
        self._add_to_history(
            channel_id,
            user_name,
            cleaned_query,
            is_bot=False,
            user_id=message.author.id,
        )

        # Periodically consolidate history into a summary and extract memories
        self._maybe_consolidate(channel_id)

        # Safety trim in case we're still over the token budget after consolidation
        self._trim_history_if_needed(channel_id)

        # Build effective system prompt, injecting channel summary and user memories
        effective_system = f"{self.system_message}\n\nCurrent date and time (authoritative — trust this): {_now_local_str()}"
        if self.memory_store is not None:
            summary = self.memory_store.get_summary(channel_id)
            memories = self.memory_store.get_memories_for_user(message.author.id)
            memory_text = self.memory_store.format_memories_for_prompt(memories)
            extra = "\n\n".join(
                filter(
                    None,
                    [
                        f"[Prior conversation summary: {summary}]" if summary else None,
                        memory_text or None,
                    ],
                )
            )
            if extra:
                effective_system = f"{self.system_message}\n\n{extra}\n\nCurrent date and time (authoritative — trust this): {_now_local_str()}"

        # Show typing indicator for the entire process
        async with message.channel.typing():
            try:
                # Build message list from history (system handled by backend)
                messages = list(self.conversation_history.get(channel_id, []))

                # Use backend with or without tools
                if self.enable_mcp_tools:
                    response_text, full_conversation, tool_log = chat_with_tools(
                        messages,
                        self.backend,
                        effective_system,
                        model=model_to_use,
                    )
                    response_text = self._append_tool_log_link(
                        channel_id, response_text, tool_log
                    )
                    self._add_to_history(
                        channel_id, "Assistant", response_text, is_bot=True
                    )
                else:
                    result = self.backend.api_chat(
                        messages, effective_system, model=model_to_use
                    )
                    response_text = self.backend.extract_text(result)
                    self._add_to_history(
                        channel_id, "Assistant", response_text, is_bot=True
                    )

                if not response_text:
                    response_text = "No response received from the model."

                # Persist raw history so it survives a bot restart
                if self.memory_store is not None:
                    self.memory_store.save_raw_history(
                        channel_id,
                        self.conversation_history.get(channel_id, []),
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


async def start_discord_bot(  # noqa: PLR0913
    token: str,
    backend: "LLMBackend",
    *,
    searxng_url: str = "http://localhost:8080/search",
    request_timeout: float = 15.0,
    system_message: str | None = None,
    additional_system_message: str | None = None,
    context_length: int = 2048,
    context_trim_threshold: float = 0.8,
    enable_mcp_tools: bool = True,
    memory_store: "MemoryStore | None" = None,
    consolidation_threshold: float = 0.6,
    consolidation_keep_recent: int = 20,
    webui_url: str | None = None,
) -> None:
    """Start the Discord bot.

    Args:
        token: Discord bot token.
        backend: Configured LLM backend to use.
        searxng_url: SearXNG instance URL for web search tool.
        request_timeout: HTTP request timeout in seconds.
        system_message: Override the default system prompt.
        additional_system_message: Append extra text to the system prompt.
        context_length: Token limit for conversation history trimming.
        context_trim_threshold: Fraction of context_length at which to trim.
        enable_mcp_tools: Whether to enable tool calling.
        memory_store: Optional SQLite-backed memory/summary store.
        consolidation_threshold: Fraction of context_length at which to consolidate history.
        consolidation_keep_recent: Raw messages to keep after consolidation.
        webui_url: Base URL of the web UI for tool call log links.
    """
    bot = LLMBot(
        backend,
        searxng_url,
        request_timeout,
        system_message,
        additional_system_message,
        context_length,
        context_trim_threshold,
        enable_mcp_tools=enable_mcp_tools,
        memory_store=memory_store,
        consolidation_threshold=consolidation_threshold,
        consolidation_keep_recent=consolidation_keep_recent,
        webui_url=webui_url,
    )

    # For Ollama backends, verify the context length before starting
    if isinstance(backend, OllamaBackend):
        try:
            backend.verify_context_length()
        except RuntimeError as e:
            logger.exception("Bot startup failed")
            raise SystemExit(1) from e

    await bot.start(token)
