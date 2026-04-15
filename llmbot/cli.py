"""This module provides the CLI functionality for our package."""

import asyncio
import os
from pathlib import Path

import click  # type: ignore[import-not-found]
import uvicorn  # type: ignore[import-untyped]

from .backends import ClaudeBackend, LLMBackend, OllamaBackend
from .caldav_tools import get_caldav_context
from .discord_bot import start_discord_bot
from .gcal_tools import get_gcal_context
from .mcp import start_mcp_server  # type: ignore[import-untyped]
from .memory import MemoryStore
from .tools import chat_with_tools, set_tool_config
from .webui import create_app


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
            response, _, _tl = chat_with_tools(messages, llm_backend, system)
        click.echo(response)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise click.Abort from e


@main.command()
@click.option(
    "--host",
    default="http://localhost:11434",
    envvar="OLLAMA_HOST",
    help="Ollama server host (also reads OLLAMA_HOST)",
)
@click.option(
    "--model",
    default=None,
    envvar="LLMBOT_MODEL",
    help="Model to use (also reads LLMBOT_MODEL; backend-specific default if omitted)",
)
@click.option(
    "--searxng-url",
    default="http://localhost:8080/search",
    envvar="SEARXNG_URL",
    help="SearXNG instance URL for web search (also reads SEARXNG_URL)",
)
@click.option(
    "--timeout",
    default=15.0,
    envvar="REQUEST_TIMEOUT",
    help="Request timeout in seconds (also reads REQUEST_TIMEOUT)",
)
@click.option(
    "--system-message",
    default=None,
    envvar="SYSTEM_MESSAGE",
    help="Additional system message content (also reads SYSTEM_MESSAGE)",
)
@click.option(
    "--system-message-file",
    type=click.Path(exists=True, readable=True),
    envvar="SYSTEM_MESSAGE_FILE",
    help="Path to file containing additional system message content (also reads SYSTEM_MESSAGE_FILE)",
)
@click.option("--no-tools", is_flag=True, help="Disable MCP tools integration")
@click.option(
    "--backend",
    type=click.Choice(["ollama", "claude"]),
    default="ollama",
    envvar="LLMBOT_BACKEND",
    help="LLM backend to use (also reads LLMBOT_BACKEND)",
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
    envvar="CONTEXT_LENGTH",
    help="Context window size for history trimming (and Ollama num_ctx; also reads CONTEXT_LENGTH)",
)
@click.option(
    "--db-path",
    default=None,
    envvar="LLMBOT_DB_PATH",
    help="SQLite memory DB path (default: ~/.local/share/llmbot/memory.db)",
)
@click.option(
    "--consolidation-threshold",
    default=0.6,
    envvar="CONSOLIDATION_THRESHOLD",
    help="Fraction of context_length at which to consolidate history (also reads CONSOLIDATION_THRESHOLD)",
)
@click.option(
    "--no-memory", is_flag=True, help="Disable persistent memory and summaries"
)
@click.option("--no-webui", is_flag=True, help="Disable the web UI admin panel")
@click.option(
    "--webui-host",
    default="127.0.0.1",
    envvar="WEBUI_HOST",
    help="Web UI bind host (also reads WEBUI_HOST)",
    show_default=True,
)
@click.option(
    "--webui-port",
    default=8080,
    type=int,
    envvar="WEBUI_PORT",
    help="Web UI bind port (also reads WEBUI_PORT)",
    show_default=True,
)
@click.option(
    "--webui-url",
    default=None,
    envvar="WEBUI_URL",
    help="Override base URL for web UI links in Discord messages (also reads WEBUI_URL)",
)
def discord(  # noqa: C901, PLR0912, PLR0913, PLR0915
    host: str,
    model: str | None,
    searxng_url: str,
    timeout: float,
    system_message: str | None,
    system_message_file: str | None,
    *,
    no_tools: bool,
    backend: str,
    api_key: str | None,
    context_length: int,
    db_path: str | None,
    consolidation_threshold: int,
    no_memory: bool,
    no_webui: bool,
    webui_host: str,
    webui_port: int,
    webui_url: str | None,
) -> None:
    """Start the Discord bot."""
    discord_token = os.getenv("DISCORD_BOT_TOKEN")
    if not discord_token:
        click.echo("Error: DISCORD_BOT_TOKEN environment variable not set", err=True)
        raise click.Abort

    llm_backend = _require_claude_backend(backend, api_key, model, host, context_length)

    additional_system_message = system_message or None
    if system_message_file:
        try:
            file_content = Path(system_message_file).read_text(encoding="utf-8").strip()
            additional_system_message = (
                f"{additional_system_message}\n\n{file_content}"
                if additional_system_message
                else file_content
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

    gcal_context = get_gcal_context()
    if gcal_context:
        click.echo(f"Google Calendar context loaded: {gcal_context}")
        additional_system_message = (
            f"{additional_system_message}\n\n{gcal_context}"
            if additional_system_message
            else gcal_context
        )

    memory_store = None
    if not no_memory:
        resolved_db_path = (
            Path(db_path) if db_path else Path.home() / ".local/share/llmbot/memory.db"
        )
        memory_store = MemoryStore(resolved_db_path)
        memory_store.initialize()
        click.echo(f"Memory store initialized at {resolved_db_path}")

    if memory_store is None:
        webui_url = None
    elif webui_url is not None:
        pass  # use the override as-is
    elif not no_webui:
        webui_url = f"http://{webui_host}:{webui_port}"
    else:
        webui_url = None
    bot_coro = start_discord_bot(
        discord_token,
        llm_backend,
        searxng_url=searxng_url,
        request_timeout=timeout,
        additional_system_message=additional_system_message,
        context_length=context_length,
        enable_mcp_tools=not no_tools,
        memory_store=memory_store,
        consolidation_threshold=consolidation_threshold,
        webui_url=webui_url,
    )

    click.echo("Starting Discord bot...")
    try:
        if no_webui or memory_store is None:
            if not no_webui and memory_store is None:
                click.echo(
                    "Web UI disabled: requires memory store (--no-memory was set)"
                )
            asyncio.run(bot_coro)
        else:
            webui_app = create_app(memory_store)
            config = uvicorn.Config(
                webui_app, host=webui_host, port=webui_port, log_level="warning"
            )
            server = uvicorn.Server(config)
            click.echo(f"Web UI available at http://{webui_host}:{webui_port}/")

            async def _run() -> None:
                await asyncio.gather(bot_coro, server.serve())

            asyncio.run(_run())
    except KeyboardInterrupt:
        click.echo("\nBot stopped by user")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise click.Abort from e


@main.command("gcal-auth")
@click.option(
    "--client-id",
    default=None,
    envvar="GOOGLE_CLIENT_ID",
    help="Google OAuth client ID (also reads GOOGLE_CLIENT_ID)",
)
@click.option(
    "--client-secret",
    default=None,
    envvar="GOOGLE_CLIENT_SECRET",
    help="Google OAuth client secret (also reads GOOGLE_CLIENT_SECRET)",
)
def gcal_auth(client_id: str | None, client_secret: str | None) -> None:
    """Run the Google OAuth flow and print credentials for .envrc."""
    try:
        from google_auth_oauthlib.flow import (  # noqa: PLC0415
            InstalledAppFlow,  # type: ignore[import-untyped]
        )
    except ImportError:
        click.echo(
            "Error: google-auth-oauthlib is required. Install it with:"
            " pip install google-auth-oauthlib",
            err=True,
        )
        raise click.Abort from None

    if not client_id:
        click.echo("Error: --client-id or GOOGLE_CLIENT_ID is required", err=True)
        raise click.Abort
    if not client_secret:
        click.echo(
            "Error: --client-secret or GOOGLE_CLIENT_SECRET is required", err=True
        )
        raise click.Abort

    from .google_auth import GOOGLE_SCOPES  # noqa: PLC0415

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob", "http://localhost"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        },
    }
    flow = InstalledAppFlow.from_client_config(client_config, scopes=GOOGLE_SCOPES)
    credentials = flow.run_local_server(port=0)

    click.echo("\nAdd these to your .envrc:\n")
    click.echo(f'export GOOGLE_CLIENT_ID="{credentials.client_id}"')
    click.echo(f'export GOOGLE_CLIENT_SECRET="{credentials.client_secret}"')
    click.echo(f'export GOOGLE_REFRESH_TOKEN="{credentials.refresh_token}"')


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


@main.command()
@click.option(
    "--db-path",
    default=None,
    envvar="LLMBOT_DB_PATH",
    help="SQLite memory DB path (default: ~/.local/share/llmbot/memory.db)",
)
@click.option("--host", default="127.0.0.1", help="Bind host")
@click.option("--port", default=8080, type=int, help="Bind port")
def webui(db_path: str | None, host: str, port: int) -> None:
    """Start the web UI admin panel."""
    resolved_db_path = (
        Path(db_path) if db_path else Path.home() / ".local/share/llmbot/memory.db"
    )
    memory_store = MemoryStore(resolved_db_path)
    memory_store.initialize()
    click.echo(f"Memory store: {resolved_db_path}")
    click.echo(f"Starting web UI at http://{host}:{port}/")
    app = create_app(memory_store)
    uvicorn.run(app, host=host, port=port)
