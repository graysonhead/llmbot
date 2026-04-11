"""MCP client integration for llmbot."""

import logging
import types
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mcp import ClientSession, StdioServerParameters  # type: ignore[import-not-found]
from mcp.client.stdio import stdio_client  # type: ignore[import-not-found]

if TYPE_CHECKING:
    from .backends import LLMBackend

logger = logging.getLogger(__name__)


class LlmbotMCPClient:
    """MCP client that connects to the llmbot MCP server and an LLM backend."""

    def __init__(self) -> None:
        """Initialize the MCP client."""
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
        server_script = Path(__file__).parent / "mcp.py"

        logger.info("Connecting to llmbot MCP server: %s", server_script)

        server_params = StdioServerParameters(
            command="python", args=[str(server_script)]
        )

        try:
            self._mcp_context = stdio_client(server_params)  # type: ignore[assignment]
            read_stream, write_stream = await self._mcp_context.__aenter__()  # type: ignore[attr-defined]
            self.session = ClientSession(read_stream, write_stream)

            await self.session.initialize()

            tools_result = await self.session.list_tools()

            logger.info("Connected to MCP server. Available tools:")
            for tool in tools_result.tools:
                logger.info("  - %s: %s", tool.name, tool.description)

                # Store tools in Ollama/OpenAI format (backends normalize as needed)
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
            tool_name: Name of the tool to call.
            arguments: Arguments to pass to the tool.

        Returns:
            String result from the tool.
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
        messages: list[dict[str, Any]],
        backend: "LLMBackend",
        system: str,
        model: str | None = None,
    ) -> str:
        """Chat using MCP tools with any LLM backend.

        Args:
            messages: Conversation history (without system message).
            backend: LLM backend to use for API calls.
            system: System prompt.
            model: Override model name, or None to use the backend default.

        Returns:
            Final response from the model.
        """
        if not self.tools:
            logger.info("No MCP tools available, using regular chat")
            result = backend.api_chat(messages, system, model=model)
            return backend.extract_text(result)

        backend_tools = backend.normalize_tools(self.tools)
        logger.info(
            "Sending message to backend with %d MCP tools available", len(backend_tools)
        )

        response = backend.api_chat(messages, system, tools=backend_tools, model=model)
        tool_calls = backend.extract_tool_calls(response)

        if tool_calls:
            logger.info("Model requested %d tool calls", len(tool_calls))

            conversation = messages.copy()
            conversation.append(backend.make_assistant_message(response))

            for tc in tool_calls:
                logger.info(
                    "Executing MCP tool call: %s(%s)", tc["name"], tc["arguments"]
                )
                tool_result = await self.call_mcp_tool(tc["name"], tc["arguments"])
                conversation.append(
                    backend.make_tool_result_message(tc["id"], tool_result)
                )

            final_response = backend.api_chat(conversation, system, model=model)
            return backend.extract_text(final_response)

        return backend.extract_text(response)
