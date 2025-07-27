"""This module provides the CLI functionality for our package."""

import os

import click
from openai import OpenAI


@click.command()
@click.option("--server-url", required=True, help="OpenWebUI server URL")
@click.option("--model", default="llama3.1:8b", help="Model to use for the query")
@click.argument("query")
def main(server_url: str, model: str, query: str) -> None:
    """Send a query to OpenWebUI and print the response."""
    api_key = os.getenv("OPENWEBUI_API_KEY")
    if not api_key:
        click.echo("Error: OPENWEBUI_API_KEY environment variable not set", err=True)
        raise click.Abort

    try:
        client = OpenAI(base_url=server_url, api_key=api_key)
        response = client.chat.completions.create(
            model=model, messages=[{"role": "user", "content": query}]
        )
        click.echo(response.choices[0].message.content)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise click.Abort from e
