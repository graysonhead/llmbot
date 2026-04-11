"""This module provides the CLI functionality for our package."""

import asyncio
import os
from pathlib import Path

import click  # type: ignore[import-not-found]

from .backends import ClaudeBackend, LLMBackend, OllamaBackend
from .caldav_tools import get_caldav_context
from .discord_bot import start_discord_bot
from .mcp import start_mcp_server  # type: ignore[import-untyped]
from .memory import MemoryStore
from .tools import chat_with_tools, set_tool_config


def _require_claude_backend(
    backend: str,
    api_key: str | None,
    model: str | None,
    host: str,
    context_length: int,
) -> LLMBackend:
    """Build and return a configured LLM backend, aborting on missing config.

    Args:
        backend: Backend name ('ollama' or 'claude').
        api_key: Anthropic API key (required when backend is 'claude').
        model: Model name/ID override, or None to use the backend default.
        host: Ollama server host URL.
        context_length: Ollama context window size.

    Returns:
        Configured LLMBackend instance.
    """
    if backend == "claude":
        if not api_key:
            click.echo(
                "Error: --api-key or ANTHROPIC_API_KEY is required"
                " for --backend claude",
                err=True,
            )
            raise click.Abort
        return ClaudeBackend(api_key=api_key, model=model or "claude-sonnet-4-6")
    return OllamaBackend(
        host=host, model=model or "llama3.1:8b", context_length=context_length
    )


@click.group()
def main() -> None:
    """LLM Gateway for Discord - Connect Discord users to LLMs via Ollama or Claude."""


@main.command()
@click.option("--host", default="http://localhost:11434", help="Ollama server host")
@click.option(
    "--model", default=None, help="Model to use (backend-specific default if omitted)"
)
@click.option(
    "--searxng-url",
    default="http://localhost:8080/search",
    help="SearXNG instance URL for web search",
)
@click.option("--no-tools", is_flag=True, help="Disable MCP tools integration")
@click.option(
    "--backend",
    type=click.Choice(["ollama", "claude"]),
    default="ollama",
    help="LLM backend to use",
)
@click.option(
    "--api-key",
    default=None,
    envvar="ANTHROPIC_API_KEY",
    help="Anthropic API key (for --backend claude; also reads ANTHROPIC_API_KEY)",
)
@click.option(
    "--context-length",
    default=2048,
    help="Context window size (for --backend ollama)",
)
@click.argument("query")
def query(  # noqa: PLR0913
    host: str,
    model: str | None,
    searxng_url: str,
    *,
    no_tools: bool,
    backend: str,
    api_key: str | None,
    context_length: int,
    query: str,
) -> None:
    """Send a query to an LLM backend and print the response."""
    llm_backend = _require_claude_backend(backend, api_key, model, host, context_length)
    system = ""
    messages = [{"role": "user", "content": query}]
    try:
        if no_tools:
            result = llm_backend.api_chat(messages, system)
            response = llm_backend.extract_text(result)
        else:
            set_tool_config(searxng_url)
            response, _ = chat_with_tools(messages, llm_backend, system)
        click.echo(response)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise click.Abort from e


@main.command()
@click.option("--host", default="http://localhost:11434", help="Ollama server host")
@click.option(
    "--model", default=None, help="Model to use (backend-specific default if omitted)"
)
@click.option(
    "--searxng-url",
    default="http://localhost:8080/search",
    help="SearXNG instance URL for web search",
)
@click.option("--timeout", default=15.0, help="Request timeout in seconds")
@click.option(
    "--system-message-file",
    type=click.Path(exists=True, readable=True),
    help="Path to file containing additional system message content",
)
@click.option("--no-tools", is_flag=True, help="Disable MCP tools integration")
@click.option(
    "--backend",
    type=click.Choice(["ollama", "claude"]),
    default="ollama",
    help="LLM backend to use",
)
@click.option(
    "--api-key",
    default=None,
    envvar="ANTHROPIC_API_KEY",
    help="Anthropic API key (for --backend claude; also reads ANTHROPIC_API_KEY)",
)
@click.option(
    "--context-length",
    default=2048,
    help="Context window size for history trimming (and Ollama num_ctx)",
)
@click.option(
    "--db-path",
    default=None,
    envvar="LLMBOT_DB_PATH",
    help="SQLite memory DB path (default: ~/.local/share/llmbot/memory.db)",
)
@click.option(
    "--consolidation-interval",
    default=20,
    help="Number of messages between memory consolidations",
)
@click.option(
    "--no-memory", is_flag=True, help="Disable persistent memory and summaries"
)
def discord(  # noqa: PLR0913
    host: str,
    model: str | None,
    searxng_url: str,
    timeout: float,
    system_message_file: str | None,
    *,
    no_tools: bool,
    backend: str,
    api_key: str | None,
    context_length: int,
    db_path: str | None,
    consolidation_interval: int,
    no_memory: bool,
) -> None:
    """Start the Discord bot."""
    discord_token = os.getenv("DISCORD_BOT_TOKEN")
    if not discord_token:
        click.echo("Error: DISCORD_BOT_TOKEN environment variable not set", err=True)
        raise click.Abort

    llm_backend = _require_claude_backend(backend, api_key, model, host, context_length)

    additional_system_message = None
    if system_message_file:
        try:
            additional_system_message = (
                Path(system_message_file).read_text(encoding="utf-8").strip()
            )
        except Exception as e:
            click.echo(f"Error reading system message file: {e}", err=True)
            raise click.Abort from e

    caldav_context = get_caldav_context()
    if caldav_context:
        click.echo(f"CalDAV context loaded: {caldav_context}")
        additional_system_message = (
            f"{additional_system_message}\n\n{caldav_context}"
            if additional_system_message
            else caldav_context
        )

    memory_store = None
    if not no_memory:
        resolved_db_path = (
            Path(db_path) if db_path else Path.home() / ".local/share/llmbot/memory.db"
        )
        memory_store = MemoryStore(resolved_db_path)
        memory_store.initialize()
        click.echo(f"Memory store initialized at {resolved_db_path}")

    click.echo("Starting Discord bot...")
    try:
        asyncio.run(
            start_discord_bot(
                discord_token,
                llm_backend,
                searxng_url=searxng_url,
                request_timeout=timeout,
                additional_system_message=additional_system_message,
                context_length=context_length,
                enable_mcp_tools=not no_tools,
                memory_store=memory_store,
                consolidation_interval=consolidation_interval,
            )
        )
    except KeyboardInterrupt:
        click.echo("\nBot stopped by user")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise click.Abort from e


@main.command()
def mcp() -> None:
    """Start the MCP server for tool integration."""
    click.echo("Starting MCP server...")
    try:
        asyncio.run(start_mcp_server())
    except KeyboardInterrupt:
        click.echo("\nMCP server stopped by user")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise click.Abort from e
