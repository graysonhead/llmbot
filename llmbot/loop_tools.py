"""Loop management and Discord info tools for llmbot.

Frequency format (all times are UTC):

- ``every:15m``            — every 15 minutes
- ``every:2h``             — every 2 hours
- ``every:1d``             — every 1 day
- ``daily@08:00``          — daily at 08:00 UTC
- ``weekdays@08:00``       -- Monday-Friday at 08:00 UTC
- ``weekly:monday@08:00``  — every Monday at 08:00 UTC

Day names for ``weekly:`` are case-insensitive:
monday, tuesday, wednesday, thursday, friday, saturday, sunday.
"""

import asyncio
import json
import logging
import re
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .memory import MemoryStore

_PROMPT_PREVIEW_LEN = 80
_WEEKEND_START = 5  # Saturday weekday number; Sunday is 6

logger = logging.getLogger(__name__)

# Supported day names for weekly frequency
_DAY_NAMES = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

# Injected at bot startup via set_loop_tool_config()
_loop_tool_config: dict[str, Any] = {
    "discord_client": None,
    "loop_store": None,
}

# Thread-local storage for the currently-executing loop
_current_loop: threading.local = threading.local()


def set_current_loop(loop_data: dict[str, Any]) -> None:
    """Store the currently-executing loop in thread-local storage.

    Args:
        loop_data: The loop dict passed to :func:`execute_loop`.
    """
    _current_loop.data = loop_data


def clear_current_loop() -> None:
    """Remove the current loop from thread-local storage after execution."""
    _current_loop.data = None


def set_loop_tool_config(discord_client: object, loop_store: "MemoryStore") -> None:
    """Inject the Discord client and loop store into tool config.

    Args:
        discord_client: The running discord.Client instance.
        loop_store: The MemoryStore instance backed by SQLite.
    """
    _loop_tool_config["discord_client"] = discord_client
    _loop_tool_config["loop_store"] = loop_store


def is_valid_frequency(frequency: str) -> bool:
    """Return True if *frequency* matches a supported format.

    Args:
        frequency: The frequency string to validate.

    Returns:
        True if the format is recognised, False otherwise.
    """
    if re.fullmatch(r"every:\d+[mhd]", frequency):
        return True
    if re.fullmatch(r"daily@\d{2}:\d{2}", frequency):
        return True
    if re.fullmatch(r"weekdays@\d{2}:\d{2}", frequency):
        return True
    m = re.fullmatch(r"weekly:(\w+)@\d{2}:\d{2}", frequency)
    return bool(m and m.group(1).lower() in _DAY_NAMES)


def compute_next_run(frequency: str, after: datetime | None = None) -> datetime:
    """Return the next UTC datetime this frequency fires after *after*.

    Args:
        frequency: A frequency string in the supported format.
        after: Reference UTC datetime; defaults to ``datetime.now(UTC)``.

    Returns:
        UTC-aware datetime of the next scheduled execution.

    Raises:
        ValueError: If *frequency* is not a recognised format.
    """
    base = (after or datetime.now(UTC)).astimezone(UTC)

    # every:Nm / every:Nh / every:Nd
    m = re.fullmatch(r"every:(\d+)([mhd])", frequency)
    if m:
        amount = int(m.group(1))
        unit = m.group(2)
        delta = (
            timedelta(minutes=amount)
            if unit == "m"
            else timedelta(hours=amount)
            if unit == "h"
            else timedelta(days=amount)
        )
        return base + delta

    def _next_time_of_day(ref: datetime, hour: int, minute: int) -> datetime:
        """Return the next occurrence of HH:MM UTC on or after *ref*."""
        candidate = ref.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= ref:
            candidate += timedelta(days=1)
        return candidate

    # daily@HH:MM
    m = re.fullmatch(r"daily@(\d{2}):(\d{2})", frequency)
    if m:
        return _next_time_of_day(base, int(m.group(1)), int(m.group(2)))

    # weekdays@HH:MM
    m = re.fullmatch(r"weekdays@(\d{2}):(\d{2})", frequency)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
        candidate = _next_time_of_day(base, hour, minute)
        while candidate.weekday() >= _WEEKEND_START:  # advance past Sat/Sun
            candidate += timedelta(days=1)
        return candidate

    # weekly:DAY@HH:MM
    m = re.fullmatch(r"weekly:(\w+)@(\d{2}):(\d{2})", frequency)
    if m and m.group(1).lower() in _DAY_NAMES:
        target_day = _DAY_NAMES[m.group(1).lower()]
        hour, minute = int(m.group(2)), int(m.group(3))
        candidate = _next_time_of_day(base, hour, minute)
        while candidate.weekday() != target_day:
            candidate += timedelta(days=1)
        return candidate

    msg = f"Unrecognised frequency format: {frequency!r}"
    raise ValueError(msg)


# ── Discord info tools ───────────────────────────────────────────────────────


def discord_list_channels() -> str:
    """List all text channels visible to the bot across all guilds.

    Returns:
        JSON string with a list of ``{id, name, type, guild}`` objects,
        or an error message if the Discord client is not available.
    """
    client = _loop_tool_config.get("discord_client")
    if client is None:
        return "Error: Discord client not available."
    channels = []
    for guild in client.guilds:
        for ch in guild.channels:
            channels.append(  # noqa: PERF401
                {
                    "id": ch.id,
                    "name": ch.name,
                    "type": str(ch.type),
                    "guild": guild.name,
                }
            )
    return json.dumps(channels, indent=2)


def discord_list_members(guild_id: int = 0) -> str:
    """List cached guild members.

    If *guild_id* is 0 (or omitted), the first guild the bot is in is used.

    Note: Requires the Members privileged intent to be enabled in the Discord
    Developer Portal and in the bot's intents.

    Args:
        guild_id: Optional Discord guild (server) snowflake.

    Returns:
        JSON string with a list of ``{id, display_name, mention}`` objects,
        or an error message.
    """
    client = _loop_tool_config.get("discord_client")
    if client is None:
        return "Error: Discord client not available."
    if not client.guilds:
        return "Error: Bot is not in any guilds."
    if guild_id:
        guild = client.get_guild(guild_id)
        if guild is None:
            return f"Error: Guild {guild_id} not found."
    else:
        guild = client.guilds[0]
    members = [
        {
            "id": m.id,
            "display_name": m.display_name,
            "mention": m.mention,
        }
        for m in guild.members
        if not m.bot
    ]
    return json.dumps(members, indent=2)


# ── Loop CRUD tools ──────────────────────────────────────────────────────────


def loop_list() -> str:
    """List all configured loops.

    Returns:
        Human-readable summary of all loops, or a message if none exist.
    """
    store: MemoryStore | None = _loop_tool_config.get("loop_store")
    if store is None:
        return "Error: Loop store not available."
    loops = store.list_loops()
    if not loops:
        return "No loops configured."
    lines = []
    for lp in loops:
        status = "enabled" if lp["enabled"] else "disabled"
        model_info = f", model={lp['model']}" if lp["model"] else ""
        target_info = f", target={lp['target']}" if lp["target"] else ""
        lines.append(
            f"[{lp['id']}] {lp['name']} ({status})\n"
            f"  frequency: {lp['frequency']}\n"
            f"  channel: {lp['output_channel']}{target_info}{model_info}\n"
            f"  next_run: {lp['next_run']}\n"
            f"  prompt: {lp['prompt'][:_PROMPT_PREVIEW_LEN]}"
            f"{'...' if len(lp['prompt']) > _PROMPT_PREVIEW_LEN else ''}"
        )
    return "\n\n".join(lines)


def loop_create(  # noqa: PLR0913
    name: str,
    frequency: str,
    prompt: str,
    output_channel: int,
    target: str = "",
    model: str = "",
) -> str:
    """Create a new loop.

    Args:
        name: Human-readable loop name.
        frequency: Frequency string, e.g. ``"daily@08:00"``, ``"every:15m"``,
                   ``"weekdays@09:00"``, ``"weekly:monday@08:00"``.
        prompt: The system prompt that drives the loop's LLM call.
        output_channel: Discord channel ID (integer snowflake) to post results to.
        target: Optional mention prepended to the response, e.g. ``"@everyone"``
                or ``"<@123456789>"``.
        model: Optional model override; empty string means use the bot's default.

    Returns:
        Success message with the new loop id, or an error description.
    """
    store: MemoryStore | None = _loop_tool_config.get("loop_store")
    if store is None:
        return "Error: Loop store not available."
    if not is_valid_frequency(frequency):
        return (
            f"Error: '{frequency}' is not a recognised frequency. "
            "Examples: 'every:15m', 'daily@08:00', 'weekdays@09:00', 'weekly:monday@08:00'."
        )
    try:
        next_run = compute_next_run(frequency)
        loop_id = store.create_loop(
            name=name,
            frequency=frequency,
            prompt=prompt,
            output_channel=output_channel,
            next_run=next_run,
            target=target,
            model=model,
        )
    except Exception as exc:
        logger.exception("loop_create failed")
        return f"Error creating loop: {exc}"
    return (
        f"Loop '{name}' created with id={loop_id}. "
        f"Next run: {next_run.strftime('%Y-%m-%d %H:%M UTC')}."
    )


def loop_update(  # noqa: C901, PLR0913
    loop_id: int,
    name: str = "",
    frequency: str = "",
    prompt: str = "",
    output_channel: int = 0,
    target: str = "",
    model: str = "",
) -> str:
    """Update fields on an existing loop.

    Only non-empty / non-zero arguments are applied. If *frequency* is updated,
    *next_run* is automatically recomputed.

    Args:
        loop_id: The id of the loop to update.
        name: New human-readable name (leave empty to keep current).
        frequency: New frequency string (leave empty to keep current).
        prompt: New system prompt (leave empty to keep current).
        output_channel: New channel id (pass 0 to keep current).
        target: New mention string (pass empty string to keep current).
        model: New model override (pass empty string to keep current).

    Returns:
        Success message or an error description.
    """
    store: MemoryStore | None = _loop_tool_config.get("loop_store")
    if store is None:
        return "Error: Loop store not available."
    fields: dict[str, Any] = {}
    if name:
        fields["name"] = name
    if frequency:
        if not is_valid_frequency(frequency):
            return (
                f"Error: '{frequency}' is not a recognised frequency. "
                "Examples: 'every:15m', 'daily@08:00', 'weekdays@09:00', 'weekly:monday@08:00'."
            )
        fields["frequency"] = frequency
        fields["next_run"] = compute_next_run(frequency).strftime("%Y-%m-%dT%H:%M:%S")
    if prompt:
        fields["prompt"] = prompt
    if output_channel:
        fields["output_channel"] = output_channel
    if target:
        fields["target"] = target
    if model:
        fields["model"] = model
    if not fields:
        return "No fields to update were provided."
    updated = store.update_loop(loop_id, **fields)
    if not updated:
        return f"Error: Loop id={loop_id} not found."
    return f"Loop id={loop_id} updated: {', '.join(fields.keys())}."


def loop_delete(loop_id: int) -> str:
    """Delete a loop permanently.

    Args:
        loop_id: The id of the loop to delete.

    Returns:
        Success message or an error description.
    """
    store: MemoryStore | None = _loop_tool_config.get("loop_store")
    if store is None:
        return "Error: Loop store not available."
    if store.delete_loop(loop_id):
        return f"Loop id={loop_id} deleted."
    return f"Error: Loop id={loop_id} not found."


def loop_enable(loop_id: int) -> str:
    """Enable a loop and recompute its next_run from now.

    Args:
        loop_id: The id of the loop to enable.

    Returns:
        Success message or an error description.
    """
    store: MemoryStore | None = _loop_tool_config.get("loop_store")
    if store is None:
        return "Error: Loop store not available."
    lp = store.get_loop(loop_id)
    if lp is None:
        return f"Error: Loop id={loop_id} not found."
    next_run = compute_next_run(lp["frequency"])
    store.update_loop(
        loop_id,
        enabled=1,
        next_run=next_run.strftime("%Y-%m-%dT%H:%M:%S"),
    )
    return (
        f"Loop id={loop_id} enabled. "
        f"Next run: {next_run.strftime('%Y-%m-%d %H:%M UTC')}."
    )


def loop_disable(loop_id: int) -> str:
    """Disable a loop so it no longer fires.

    Args:
        loop_id: The id of the loop to disable.

    Returns:
        Success message or an error description.
    """
    store: MemoryStore | None = _loop_tool_config.get("loop_store")
    if store is None:
        return "Error: Loop store not available."
    if store.update_loop(loop_id, enabled=0):
        return f"Loop id={loop_id} disabled."
    return f"Error: Loop id={loop_id} not found."


def loop_get_prompt(loop_id: int) -> str:
    """Return the full, untruncated prompt for a loop.

    Args:
        loop_id: The id of the loop to inspect.

    Returns:
        The complete prompt string, or an error description.
    """
    store: MemoryStore | None = _loop_tool_config.get("loop_store")
    if store is None:
        return "Error: Loop store not available."
    lp = store.get_loop(loop_id)
    if lp is None:
        return f"Error: Loop id={loop_id} not found."
    return str(lp["prompt"])


def loop_run(loop_id: int) -> str:
    """Manually trigger a loop immediately, regardless of its schedule.

    Useful for testing a loop before its scheduled time. The loop is executed
    asynchronously; the next scheduled run time is updated as if it had fired
    normally.

    Args:
        loop_id: The id of the loop to trigger.

    Returns:
        Confirmation message, or an error description.
    """
    store: MemoryStore | None = _loop_tool_config.get("loop_store")
    client = _loop_tool_config.get("discord_client")
    if store is None or client is None:
        return "Error: Loop store or Discord client not available."
    lp = store.get_loop(loop_id)
    if lp is None:
        return f"Error: Loop id={loop_id} not found."
    try:
        event_loop = asyncio.get_event_loop()
        event_loop.create_task(client.execute_loop(lp))  # noqa: RUF006
    except RuntimeError as exc:
        return f"Error scheduling loop: {exc}"
    return f"Loop id={loop_id} '{lp['name']}' triggered manually."


# ── Self-inspection tools (available during loop execution) ─────────────────


def loop_get_self() -> str:
    """Return the full details of the currently-executing loop, including the complete prompt.

    Returns:
        JSON string with all loop fields, or an error if called outside a loop context.
    """
    data = getattr(_current_loop, "data", None)
    if data is None:
        return "Error: Not running inside a loop execution context."
    return json.dumps(data, indent=2, default=str)


def loop_update_self(  # noqa: PLR0913
    name: str = "",
    frequency: str = "",
    prompt: str = "",
    output_channel: int = 0,
    target: str = "",
    model: str = "",
) -> str:
    """Update fields on the currently-executing loop.

    Only non-empty / non-zero arguments are applied. If *frequency* is updated,
    *next_run* is automatically recomputed.

    Args:
        name: New human-readable name (leave empty to keep current).
        frequency: New frequency string (leave empty to keep current).
        prompt: New system prompt (leave empty to keep current).
        output_channel: New channel id (pass 0 to keep current).
        target: New mention string (pass empty string to keep current).
        model: New model override (pass empty string to keep current).

    Returns:
        Success message or an error description.
    """
    data = getattr(_current_loop, "data", None)
    if data is None:
        return "Error: Not running inside a loop execution context."
    return loop_update(
        loop_id=data["id"],
        name=name,
        frequency=frequency,
        prompt=prompt,
        output_channel=output_channel,
        target=target,
        model=model,
    )


# ── Tool definitions (Ollama / OpenAI format) ────────────────────────────────

LOOP_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "discord_list_channels",
            "description": (
                "List all Discord channels the bot can see, with their IDs and names. "
                "Use this to find the correct channel ID when configuring a loop."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "discord_list_members",
            "description": (
                "List cached guild members (non-bot) with their IDs and mention strings. "
                "Use this to find user IDs or mention strings for loop targets."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "guild_id": {
                        "type": "integer",
                        "description": (
                            "Optional guild (server) ID. Defaults to 0 which uses "
                            "the first guild the bot is in."
                        ),
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "loop_list",
            "description": "List all configured loops with their settings and status.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "loop_create",
            "description": (
                "Create a new scheduled loop that runs an LLM prompt at a fixed interval "
                "and posts the result to a Discord channel. "
                "Frequency format (all times UTC): "
                "'every:15m' = every 15 minutes, 'every:2h' = every 2 hours, "
                "'daily@08:00' = daily at 8 AM, 'weekdays@08:00' = Mon-Fri at 8 AM, "
                "'weekly:monday@08:00' = every Monday at 8 AM."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Human-readable name for the loop.",
                    },
                    "frequency": {
                        "type": "string",
                        "description": (
                            "When to fire the loop. Supported formats: "
                            "'every:Nm' (minutes), 'every:Nh' (hours), 'every:Nd' (days), "
                            "'daily@HH:MM', 'weekdays@HH:MM', 'weekly:DAYNAME@HH:MM'. "
                            "All times are UTC."
                        ),
                    },
                    "prompt": {
                        "type": "string",
                        "description": (
                            "System prompt sent to the LLM each time the loop fires. "
                            "This should describe what output to generate."
                        ),
                    },
                    "output_channel": {
                        "type": "integer",
                        "description": "Discord channel ID (snowflake integer) to post results to.",
                    },
                    "target": {
                        "type": "string",
                        "description": (
                            "Optional mention string prepended to the response, "
                            'e.g. "@everyone" or "<@123456789>".'
                        ),
                    },
                    "model": {
                        "type": "string",
                        "description": (
                            "Optional model name override. Leave empty to use the bot's default."
                        ),
                    },
                },
                "required": ["name", "frequency", "prompt", "output_channel"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "loop_update",
            "description": (
                "Update one or more fields on an existing loop. "
                "Only provide the fields you want to change; omit the rest."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "loop_id": {
                        "type": "integer",
                        "description": "The id of the loop to update.",
                    },
                    "name": {"type": "string", "description": "New loop name."},
                    "frequency": {
                        "type": "string",
                        "description": "New frequency string (e.g. 'daily@08:00', 'every:15m').",
                    },
                    "prompt": {"type": "string", "description": "New system prompt."},
                    "output_channel": {
                        "type": "integer",
                        "description": "New Discord channel ID.",
                    },
                    "target": {
                        "type": "string",
                        "description": "New mention string or empty to clear.",
                    },
                    "model": {
                        "type": "string",
                        "description": "New model override or empty to use default.",
                    },
                },
                "required": ["loop_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "loop_delete",
            "description": "Permanently delete a loop by its id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "loop_id": {
                        "type": "integer",
                        "description": "The id of the loop to delete.",
                    },
                },
                "required": ["loop_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "loop_enable",
            "description": "Enable a disabled loop and recompute its next scheduled run.",
            "parameters": {
                "type": "object",
                "properties": {
                    "loop_id": {
                        "type": "integer",
                        "description": "The id of the loop to enable.",
                    },
                },
                "required": ["loop_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "loop_disable",
            "description": "Disable a loop so it no longer fires.",
            "parameters": {
                "type": "object",
                "properties": {
                    "loop_id": {
                        "type": "integer",
                        "description": "The id of the loop to disable.",
                    },
                },
                "required": ["loop_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "loop_get_prompt",
            "description": (
                "Return the full, untruncated system prompt for a loop. "
                "Use this when you need to read the complete prompt before editing it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "loop_id": {
                        "type": "integer",
                        "description": "The id of the loop to inspect.",
                    },
                },
                "required": ["loop_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "loop_run",
            "description": (
                "Manually trigger a loop right now, regardless of its schedule. "
                "Use this to test a loop before its scheduled time."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "loop_id": {
                        "type": "integer",
                        "description": "The id of the loop to trigger.",
                    },
                },
                "required": ["loop_id"],
            },
        },
    },
]

# Tools available only during loop execution (self-inspection / self-modification)
LOOP_SELF_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "loop_get_self",
            "description": (
                "Return the full details of the currently-executing loop, "
                "including the complete system prompt. Use this to read your "
                "own configuration before deciding whether to update it."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "loop_update_self",
            "description": (
                "Update fields on the currently-executing loop. "
                "Only provide the fields you want to change; omit the rest. "
                "Use this to modify your own prompt, frequency, or other settings."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "New loop name."},
                    "frequency": {
                        "type": "string",
                        "description": "New frequency string (e.g. 'daily@08:00', 'every:15m').",
                    },
                    "prompt": {
                        "type": "string",
                        "description": "New system prompt to replace the current one.",
                    },
                    "output_channel": {
                        "type": "integer",
                        "description": "New Discord channel ID.",
                    },
                    "target": {
                        "type": "string",
                        "description": "New mention string or empty to clear.",
                    },
                    "model": {
                        "type": "string",
                        "description": "New model override or empty to use default.",
                    },
                },
                "required": [],
            },
        },
    },
]

LOOP_SELF_TOOL_FUNCTIONS: dict[str, Callable[..., Any]] = {
    "loop_get_self": loop_get_self,
    "loop_update_self": loop_update_self,
}

LOOP_TOOL_FUNCTIONS: dict[str, Callable[..., Any]] = {
    "discord_list_channels": discord_list_channels,
    "discord_list_members": discord_list_members,
    "loop_list": loop_list,
    "loop_get_prompt": loop_get_prompt,
    "loop_create": loop_create,
    "loop_update": loop_update,
    "loop_delete": loop_delete,
    "loop_enable": loop_enable,
    "loop_disable": loop_disable,
    "loop_run": loop_run,
    **LOOP_SELF_TOOL_FUNCTIONS,
}
