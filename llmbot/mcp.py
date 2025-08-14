"""MCP server implementation for llmbot."""

import asyncio
from typing import Any

from mcp.server import Server  # type: ignore[import-not-found]
from mcp.server.models import InitializationOptions  # type: ignore[import-not-found]
from mcp.server.stdio import stdio_server  # type: ignore[import-not-found]
from mcp.types import Tool  # type: ignore[import-not-found]


async def add_numbers(a: float, b: float) -> float:
    """Add two numbers together.

    Args:
        a: First number to add
        b: Second number to add

    Returns:
        The sum of a and b
    """
    return a + b


def create_mcp_server() -> Server:
    """Create and configure the MCP server with tools."""
    server = Server("llmbot-mcp")

    @server.list_tools()
    async def handle_list_tools() -> list[Tool]:
        """List available tools."""
        return [
            Tool(
                name="add_numbers",
                description="Add two numbers together",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "a": {
                            "type": "number",
                            "description": "First number to add",
                        },
                        "b": {
                            "type": "number",
                            "description": "Second number to add",
                        },
                    },
                    "required": ["a", "b"],
                },
            )
        ]

    @server.call_tool()
    async def handle_call_tool(
        name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Handle tool calls."""
        if name == "add_numbers":
            a = arguments.get("a")
            b = arguments.get("b")
            if a is None or b is None:
                msg = "Both 'a' and 'b' parameters are required"
                raise ValueError(msg)

            result = await add_numbers(float(a), float(b))
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"The sum of {a} and {b} is {result}",
                    }
                ]
            }
        msg = f"Unknown tool: {name}"
        raise ValueError(msg)

    return server


async def start_mcp_server() -> None:
    """Start the MCP server with stdio transport."""
    server = create_mcp_server()

    options = InitializationOptions(
        server_name="llmbot-mcp",
        server_version="1.0.0",
        capabilities=server.get_capabilities(  # type: ignore[misc]
            notification_options=None,  # type: ignore[arg-type]
            experimental_capabilities=None,  # type: ignore[arg-type]
        ),
    )

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            options,
        )


def main() -> None:
    """Start the standalone MCP server."""
    asyncio.run(start_mcp_server())


if __name__ == "__main__":
    main()
