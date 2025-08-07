"""This module provides the CLI functionality for our package."""

import asyncio
import os

import click  # type: ignore[import-not-found]
from openai import OpenAI  # type: ignore[import-not-found]

from .discord_bot import start_discord_bot


@click.group()
def main() -> None:
    """LLM Gateway for Discord - Connect Discord users to LLMs via OpenWebUI."""


@main.command()
@click.option("--server-url", required=True, help="OpenWebUI server URL")
@click.option("--model", default="llama3.1:8b", help="Model to use for the query")
@click.option("--timeout", default=15.0, help="Request timeout in seconds")
@click.argument("query")
def query(server_url: str, model: str, timeout: float, query: str) -> None:
    """Send a query to OpenWebUI and print the response."""
    api_key = os.getenv("OPENWEBUI_API_KEY")
    if not api_key:
        click.echo("Error: OPENWEBUI_API_KEY environment variable not set", err=True)
        raise click.Abort

    try:
        client = OpenAI(base_url=server_url, api_key=api_key, timeout=timeout)
        response = client.chat.completions.create(
            model=model, messages=[{"role": "user", "content": query}]
        )
        content = response.choices[0].message.content
        if content:
            click.echo(content)
        else:
            click.echo("No response received from the model.")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise click.Abort from e


@main.command()
@click.option("--server-url", required=True, help="OpenWebUI server URL")
@click.option("--model", default="llama3.1:8b", help="Model to use for queries")
@click.option(
    "--context-limit",
    default=10,
    help="Number of messages to keep in context per channel",
)
@click.option("--timeout", default=15.0, help="Request timeout in seconds")
def discord(server_url: str, model: str, context_limit: int, timeout: float) -> None:
    """Start the Discord bot."""
    discord_token = os.getenv("DISCORD_BOT_TOKEN")
    if not discord_token:
        click.echo("Error: DISCORD_BOT_TOKEN environment variable not set", err=True)
        raise click.Abort

    click.echo("Starting Discord bot...")
    try:
        asyncio.run(
            start_discord_bot(
                discord_token,
                server_url,
                model=model,
                context_limit=context_limit,
                request_timeout=timeout,
            )
        )
    except KeyboardInterrupt:
        click.echo("\nBot stopped by user")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise click.Abort from e
