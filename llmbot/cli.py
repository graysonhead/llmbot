"""This module provides the CLI functionality for our package."""

import asyncio
import os
from pathlib import Path

import click  # type: ignore[import-not-found]
import ollama  # type: ignore[import-not-found]

from .discord_bot import start_discord_bot
from .mcp import start_mcp_server  # type: ignore[import-untyped]
from .tools import chat_with_tools, set_tool_config


@click.group()
def main() -> None:
    """LLM Gateway for Discord - Connect Discord users to LLMs via Ollama."""


@main.command()
@click.option("--host", default="http://localhost:11434", help="Ollama server host")
@click.option("--model", default="llama3.1:8b", help="Model to use for the query")
@click.option(
    "--searxng-url",
    default="http://localhost:8080/search",
    help="SearXNG instance URL for web search",
)
@click.option("--no-tools", is_flag=True, help="Disable MCP tools integration")
@click.argument("query")
def query(
    host: str, model: str, searxng_url: str, *, no_tools: bool, query: str
) -> None:
    """Send a query to Ollama and print the response."""
    try:
        client = ollama.Client(host=host)
        messages = [{"role": "user", "content": query}]

        if no_tools:
            # Use regular ollama without tools
            result = client.chat(model=model, messages=messages)
            response = (
                result["message"]["content"]
                if result
                else "No response received from the model."
            )
        else:
            # Configure tools with searxng URL
            set_tool_config(searxng_url)
            # Use built-in tools
            response, _ = chat_with_tools(messages, client, model)

        click.echo(response)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise click.Abort from e


@main.command()
@click.option("--host", default="http://localhost:11434", help="Ollama server host")
@click.option("--model", default="llama3.1:8b", help="Model to use for queries")
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
def discord(  # noqa: PLR0913
    host: str,
    model: str,
    searxng_url: str,
    timeout: float,
    system_message_file: str | None,
    *,
    no_tools: bool,
) -> None:
    """Start the Discord bot."""
    discord_token = os.getenv("DISCORD_BOT_TOKEN")
    if not discord_token:
        click.echo("Error: DISCORD_BOT_TOKEN environment variable not set", err=True)
        raise click.Abort

    # Read additional system message content if file is provided
    additional_system_message = None
    if system_message_file:
        try:
            additional_system_message = (
                Path(system_message_file).read_text(encoding="utf-8").strip()
            )
        except Exception as e:
            click.echo(f"Error reading system message file: {e}", err=True)
            raise click.Abort from e

    click.echo("Starting Discord bot...")
    try:
        asyncio.run(
            start_discord_bot(
                discord_token,
                ollama_host=host,
                model=model,
                searxng_url=searxng_url,
                request_timeout=timeout,
                additional_system_message=additional_system_message,
                enable_mcp_tools=not no_tools,
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
