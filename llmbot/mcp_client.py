"""MCP client integration for llmbot."""

import logging
import types
from pathlib import Path
from typing import Any

import ollama  # type: ignore[import-not-found]
from mcp import ClientSession, StdioServerParameters  # type: ignore[import-not-found]
from mcp.client.stdio import stdio_client  # type: ignore[import-not-found]

logger = logging.getLogger(__name__)


class LlmbotMCPClient:
    """MCP client that connects to llmbot MCP server and integrates with Ollama."""

    def __init__(self, model_name: str = "llama3.1:8b") -> None:
        """Initialize the MCP client.

        Args:
            model_name: Name of the Ollama model to use
        """
        self.model_name = model_name
        self.tools: list[dict[str, Any]] = []
        self.session: ClientSession | None = None
        self._mcp_context: Any = None

    async def __aenter__(self) -> "LlmbotMCPClient":
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """Async context manager exit."""
        await self.disconnect()

    async def connect(self) -> None:
        """Connect to the llmbot MCP server and load tools."""
        # Path to the MCP server script
        server_script = Path(__file__).parent / "mcp.py"

        logger.info("Connecting to llmbot MCP server: %s", server_script)

        server_params = StdioServerParameters(
            command="python", args=[str(server_script)]
        )

        try:
            # Connect to the MCP server
            self._mcp_context = stdio_client(server_params)  # type: ignore[assignment]
            read_stream, write_stream = await self._mcp_context.__aenter__()  # type: ignore[attr-defined]
            self.session = ClientSession(read_stream, write_stream)

            # Initialize the session
            await self.session.initialize()

            # Get available tools from the server
            tools_result = await self.session.list_tools()

            logger.info("Connected to MCP server. Available tools:")
            for tool in tools_result.tools:
                logger.info("  - %s: %s", tool.name, tool.description)

                # Convert MCP tool to Ollama tool format
                ollama_tool = {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.inputSchema.model_dump()
                        if hasattr(tool.inputSchema, "model_dump")
                        else tool.inputSchema,
                    },
                }
                self.tools.append(ollama_tool)

        except Exception as e:
            logger.exception("Failed to connect to MCP server")
            msg = f"Failed to connect to MCP server: {e}"
            raise RuntimeError(msg) from e

    async def disconnect(self) -> None:
        """Disconnect from the MCP server."""
        if self._mcp_context:
            try:
                await self._mcp_context.__aexit__(None, None, None)
            except Exception as e:  # noqa: BLE001
                logger.warning("Error disconnecting from MCP server: %s", e)
            finally:
                self._mcp_context = None
                self.session = None

    async def call_mcp_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Call a tool on the MCP server.

        Args:
            tool_name: Name of the tool to call
            arguments: Arguments to pass to the tool

        Returns:
            String result from the tool
        """
        if not self.session:
            msg = "MCP client not connected"
            raise RuntimeError(msg)

        try:
            logger.info("Calling MCP tool: %s with args: %s", tool_name, arguments)
            result = await self.session.call_tool(tool_name, arguments)

            if result.content:
                content = result.content[0]
                if hasattr(content, "text"):
                    tool_result = content.text  # type: ignore[attr-defined]
                    logger.info("MCP tool result: %s", tool_result)
                    return str(tool_result)
                logger.warning("MCP result content has no text attribute: %s", content)
                return str(content)
            return "No result returned from tool"  # noqa: TRY300

        except Exception as e:
            error_msg = f"Error calling MCP tool {tool_name}: {e}"
            logger.exception(error_msg)
            return error_msg

    async def chat_with_tools(
        self,
        messages: list[dict[str, str]],
        ollama_client: ollama.Client,
        **ollama_options: Any,  # noqa: ANN401
    ) -> str:
        """Chat with Ollama using MCP tools.

        Args:
            messages: List of message dictionaries for conversation
            ollama_client: Ollama client instance
            **ollama_options: Additional options to pass to Ollama

        Returns:
            Final response from the model
        """
        if not self.tools:
            # No tools available, use regular chat
            logger.info("No MCP tools available, using regular chat")
            result = ollama_client.chat(
                model=self.model_name, messages=messages, **ollama_options
            )
            return result["message"]["content"] if result else "No response received"

        logger.info(
            "Sending message to Ollama with %d MCP tools available", len(self.tools)
        )

        # Send message to Ollama with available tools
        response = ollama_client.chat(
            model=self.model_name, messages=messages, tools=self.tools, **ollama_options
        )

        # Check if model wants to use tools
        if response["message"].get("tool_calls"):
            logger.info(
                "Model requested %d tool calls", len(response["message"]["tool_calls"])
            )

            conversation = messages.copy()
            conversation.append(response["message"])

            # Execute each tool call via MCP
            for tool_call in response["message"]["tool_calls"]:
                function_name = tool_call["function"]["name"]
                function_args = tool_call["function"]["arguments"]

                logger.info("Executing tool call: %s(%s)", function_name, function_args)

                # Call the tool via MCP
                tool_result = await self.call_mcp_tool(function_name, function_args)

                # Add tool result to conversation
                conversation.append({"role": "tool", "content": str(tool_result)})

            # Get final response from Ollama with tool results
            final_response = ollama_client.chat(
                model=self.model_name, messages=conversation, **ollama_options
            )

            return (
                final_response["message"]["content"]
                if final_response
                else "No response received"
            )
        # No tools called, return original response
        return response["message"]["content"] if response else "No response received"
