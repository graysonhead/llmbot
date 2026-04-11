"""LLM backend abstractions for llmbot."""

from __future__ import annotations

import logging
from typing import Any, Protocol

import anthropic as _anthropic  # type: ignore[import-not-found]
import ollama as _ollama  # type: ignore[import-not-found]

logger = logging.getLogger(__name__)


class LLMBackend(Protocol):
    """Protocol defining the interface for LLM backends."""

    def normalize_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert tools from Ollama/OpenAI format to backend-specific format.

        Args:
            tools: Tool definitions in Ollama/OpenAI format.

        Returns:
            Tool definitions in the backend's expected format.
        """
        ...

    def api_chat(
        self,
        messages: list[dict[str, Any]],
        system: str,
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
    ) -> Any:  # noqa: ANN401
        """Make an API call to the LLM.

        Args:
            messages: Conversation history (without system message).
            system: System prompt to use.
            tools: Backend-specific tool definitions, or None.
            model: Override the backend's default model, or None.

        Returns:
            Raw backend response object.
        """
        ...

    def extract_text(self, response: Any) -> str:  # noqa: ANN401
        """Extract text content from a backend response.

        Args:
            response: Raw response from api_chat.

        Returns:
            The text content of the response.
        """
        ...

    def extract_tool_calls(self, response: Any) -> list[dict[str, Any]]:  # noqa: ANN401
        """Extract tool calls from a backend response.

        Args:
            response: Raw response from api_chat.

        Returns:
            List of dicts with 'name', 'arguments', and 'id' keys.
        """
        ...

    def make_assistant_message(self, response: Any) -> dict[str, Any]:  # noqa: ANN401
        """Create an assistant message dict from a response.

        Args:
            response: Raw response from api_chat.

        Returns:
            Message dict suitable for appending to the conversation.
        """
        ...

    def make_tool_result_message(self, tool_use_id: str, result: str) -> dict[str, Any]:
        """Create a tool result message for feeding back to the model.

        Args:
            tool_use_id: The ID of the tool call being responded to.
            result: The string result from executing the tool.

        Returns:
            Message dict with the tool result.
        """
        ...


class OllamaBackend:
    """Ollama LLM backend."""

    def __init__(
        self,
        host: str = "http://localhost:11434",
        model: str = "llama3.1:8b",
        context_length: int = 2048,
    ) -> None:
        """Initialize the Ollama backend.

        Args:
            host: Ollama server URL.
            model: Default model name.
            context_length: Context window size to request from Ollama.
        """
        self._client = _ollama.Client(host=host)
        self._model = model
        self._context_length = context_length

    def normalize_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Return tools unchanged (already in Ollama/OpenAI format).

        Args:
            tools: Tool definitions in Ollama/OpenAI format.

        Returns:
            The same tool definitions unmodified.
        """
        return tools

    def api_chat(
        self,
        messages: list[dict[str, Any]],
        system: str,
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
    ) -> Any:  # noqa: ANN401
        """Call the Ollama chat API.

        Args:
            messages: Conversation history (without system message).
            system: System prompt prepended to the message list.
            tools: Ollama-format tool definitions, or None.
            model: Override model name, or None to use the backend default.

        Returns:
            Raw Ollama response dict.
        """
        full_messages = [{"role": "system", "content": system}, *messages]
        if tools:
            return self._client.chat(  # type: ignore[return-value]
                model=model or self._model,
                messages=full_messages,  # type: ignore[arg-type]
                tools=tools,  # type: ignore[arg-type]
                options={"num_ctx": self._context_length},
            )
        return self._client.chat(  # type: ignore[return-value]
            model=model or self._model,
            messages=full_messages,  # type: ignore[arg-type]
            options={"num_ctx": self._context_length},
        )

    def extract_text(self, response: Any) -> str:  # noqa: ANN401
        """Extract text from an Ollama response.

        Args:
            response: Raw Ollama response dict.

        Returns:
            The text content of the response.
        """
        return response["message"]["content"] if response else "No response received"

    def extract_tool_calls(self, response: Any) -> list[dict[str, Any]]:  # noqa: ANN401
        """Extract tool calls from an Ollama response.

        Args:
            response: Raw Ollama response dict.

        Returns:
            List of dicts with 'name', 'arguments', and 'id' keys.
        """
        raw = response["message"].get("tool_calls") or []
        return [
            {
                "name": tc["function"]["name"],
                "arguments": tc["function"]["arguments"],
                "id": tc.get("id", ""),
            }
            for tc in raw
        ]

    def make_assistant_message(self, response: Any) -> dict[str, Any]:  # noqa: ANN401
        """Create an assistant message from an Ollama response.

        Args:
            response: Raw Ollama response dict.

        Returns:
            The message field from the response.
        """
        return response["message"]  # type: ignore[no-any-return]

    def make_tool_result_message(self, tool_use_id: str, result: str) -> dict[str, Any]:
        """Create a tool result message for Ollama.

        Args:
            tool_use_id: The ID of the tool call (may be empty string).
            result: The tool execution result.

        Returns:
            Message dict with role 'tool' and the result content.
        """
        msg: dict[str, Any] = {"role": "tool", "content": result}
        if tool_use_id:
            msg["tool_call_id"] = tool_use_id
        return msg

    def verify_context_length(self) -> None:
        """Verify that the configured context length can be set on the model.

        Raises:
            RuntimeError: If the model rejects the context length.
        """
        try:
            self._client.chat(
                model=self._model,
                messages=[{"role": "user", "content": "test"}],
                options={"num_ctx": self._context_length},
            )
        except Exception as e:
            msg = (
                f"Cannot configure context length {self._context_length} "
                f"for model {self._model}: {e}"
            )
            raise RuntimeError(msg) from e


class ClaudeBackend:
    """Anthropic Claude LLM backend."""

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-6",
    ) -> None:
        """Initialize the Claude backend.

        Args:
            api_key: Anthropic API key.
            model: Claude model ID to use.
        """
        self._client = _anthropic.Anthropic(api_key=api_key)
        self._model = model

    def normalize_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert tools from Ollama/OpenAI format to Claude format.

        Strips the 'type'/'function' wrapper and renames 'parameters' to
        'input_schema'.

        Args:
            tools: Tool definitions in Ollama/OpenAI format.

        Returns:
            Tool definitions in Claude API format.
        """
        result = []
        for tool in tools:
            if "function" in tool:
                fn = tool["function"]
                result.append(
                    {
                        "name": fn["name"],
                        "description": fn["description"],
                        "input_schema": fn["parameters"],
                    }
                )
            else:
                result.append(tool)
        return result

    def api_chat(
        self,
        messages: list[dict[str, Any]],
        system: str,
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
    ) -> Any:  # noqa: ANN401
        """Call the Claude messages API.

        Args:
            messages: Conversation history.
            system: System prompt passed as the top-level 'system' parameter.
            tools: Claude-format tool definitions, or None.
            model: Override model ID, or None to use the backend default.

        Returns:
            Raw anthropic Message response object.
        """
        if tools:
            return self._client.messages.create(  # type: ignore[return-value]
                model=model or self._model,
                system=system,
                messages=messages,  # type: ignore[arg-type]
                tools=tools,  # type: ignore[arg-type]
                max_tokens=8096,
            )
        return self._client.messages.create(  # type: ignore[return-value]
            model=model or self._model,
            system=system,
            messages=messages,  # type: ignore[arg-type]
            max_tokens=8096,
        )

    def extract_text(self, response: Any) -> str:  # noqa: ANN401
        """Extract text from a Claude response.

        Args:
            response: Raw anthropic Message response.

        Returns:
            The text content of the first text block, or a fallback message.
        """
        for block in response.content:
            if block.type == "text":
                return block.text  # type: ignore[no-any-return]
        return "No response received"

    def extract_tool_calls(self, response: Any) -> list[dict[str, Any]]:  # noqa: ANN401
        """Extract tool calls from a Claude response.

        Args:
            response: Raw anthropic Message response.

        Returns:
            List of dicts with 'name', 'arguments', and 'id' keys.
        """
        return [
            {
                "name": block.name,
                "arguments": block.input,
                "id": block.id,
            }
            for block in response.content
            if block.type == "tool_use"
        ]

    def make_assistant_message(self, response: Any) -> dict[str, Any]:  # noqa: ANN401
        """Create an assistant message from a Claude response.

        Args:
            response: Raw anthropic Message response.

        Returns:
            Message dict with role 'assistant' and the full content block list.
        """
        return {"role": "assistant", "content": response.content}

    def make_tool_result_message(self, tool_use_id: str, result: str) -> dict[str, Any]:
        """Create a tool result message for Claude.

        Args:
            tool_use_id: The ID from the tool_use block being responded to.
            result: The tool execution result.

        Returns:
            Message dict in Claude's tool_result format.
        """
        return {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": result,
                }
            ],
        }
