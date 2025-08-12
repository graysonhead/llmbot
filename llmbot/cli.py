"""This module provides the CLI functionality for our package."""

import asyncio
import os

import click  # type: ignore[import-not-found]
from openwebui_chat_client import (  # type: ignore[import-not-found,import-untyped]
    OpenWebUIClient,
)

from .discord_bot import start_discord_bot


@click.group()
def main() -> None:
    """LLM Gateway for Discord - Connect Discord users to LLMs via OpenWebUI."""


@main.command()
@click.option("--server-url", required=True, help="OpenWebUI server URL")
@click.option("--model", default="llama3.1:8b", help="Model to use for the query")
@click.argument("query")
def query(server_url: str, model: str, query: str) -> None:
    """Send a query to OpenWebUI and print the response."""
    api_key = os.getenv("OPENWEBUI_API_KEY")
    if not api_key:
        click.echo("Error: OPENWEBUI_API_KEY environment variable not set", err=True)
        raise click.Abort

    try:
        client = OpenWebUIClient(
            base_url=server_url, token=api_key, default_model_id=model
        )
        result = client.chat(question=query)
        if result and result.get("response"):
            click.echo(result["response"])
        else:
            click.echo("No response received from the model.")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise click.Abort from e


@main.command()
@click.option("--server-url", required=True, help="OpenWebUI server URL")
@click.option("--model", default="llama3.1:8b", help="Model to use for queries")
@click.option("--timeout", default=15.0, help="Request timeout in seconds")
def discord(server_url: str, model: str, timeout: float) -> None:
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
                request_timeout=timeout,
            )
        )
    except KeyboardInterrupt:
        click.echo("\nBot stopped by user")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise click.Abort from e
