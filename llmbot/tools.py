"""Simple tools integration for llmbot."""

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import ollama  # type: ignore[import-not-found]
import requests  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)

# Global tool configuration
_tool_config = {"searxng_url": "http://localhost:8080/search"}


def set_tool_config(searxng_url: str) -> None:
    """Set the tool configuration.

    Args:
        searxng_url: SearXNG instance URL to use for websearch
    """
    _tool_config["searxng_url"] = searxng_url


def add_numbers(a: float, b: float) -> int | float:
    """Add two numbers together.

    Args:
        a: First number
        b: Second number

    Returns:
        Sum of the two numbers (integer if whole number, float otherwise)
    """
    # Ensure arguments are converted to float to prevent string concatenation
    try:
        num_a = float(a)
        num_b = float(b)
        result = num_a + num_b

        # Return integer if the result is a whole number
        if result.is_integer():
            return int(result)
    except (ValueError, TypeError) as e:
        msg = f"Invalid number format: {e}"
        raise ValueError(msg) from e
    else:
        return result


def subtract_numbers(a: float, b: float) -> int | float:
    """Subtract two numbers.

    Args:
        a: First number (minuend)
        b: Second number (subtrahend)

    Returns:
        Difference of the two numbers (integer if whole number, float otherwise)
    """
    # Ensure arguments are converted to float to prevent string issues
    try:
        num_a = float(a)
        num_b = float(b)
        result = num_a - num_b

        # Return integer if the result is a whole number
        if result.is_integer():
            return int(result)
    except (ValueError, TypeError) as e:
        msg = f"Invalid number format: {e}"
        raise ValueError(msg) from e
    else:
        return result


def multiply_numbers(a: float, b: float) -> int | float:
    """Multiply two numbers.

    Args:
        a: First number
        b: Second number

    Returns:
        Product of the two numbers (integer if whole number, float otherwise)
    """
    # Ensure arguments are converted to float to prevent string issues
    try:
        num_a = float(a)
        num_b = float(b)
        result = num_a * num_b

        # Return integer if the result is a whole number
        if result.is_integer():
            return int(result)
    except (ValueError, TypeError) as e:
        msg = f"Invalid number format: {e}"
        raise ValueError(msg) from e
    else:
        return result


def divide_numbers(a: float, b: float) -> int | float:
    """Divide two numbers.

    Args:
        a: First number (dividend)
        b: Second number (divisor)

    Returns:
        Quotient of the two numbers (integer if whole number, float otherwise)

    Raises:
        ValueError: If division by zero is attempted
    """
    # Ensure arguments are converted to float to prevent string issues
    try:
        num_a = float(a)
        num_b = float(b)

        if num_b == 0:
            msg = "Division by zero is not allowed"
            raise ValueError(msg)  # noqa: TRY301

        result = num_a / num_b

        # Return integer if the result is a whole number
        if result.is_integer():
            return int(result)
    except (ValueError, TypeError) as e:
        msg = f"Invalid number format: {e}"
        raise ValueError(msg) from e
    else:
        return result


def get_current_time() -> str:
    """Get the current date and time.

    Returns:
        Current date and time formatted as a string
    """
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def get_metar(icao_code: str) -> str:
    """Get METAR weather data for an airport by ICAO code.

    Args:
        icao_code: 3 or 4-letter airport code (e.g., GTU, KGTU, KJFK)

    Returns:
        Formatted METAR data including airport name, raw observation, and attributes
    """

    def fetch_metar_data(code: str) -> dict | None:
        """Fetch METAR data for a given code."""
        try:
            url = f"https://aviationweather.gov/api/data/metar?ids={code.upper()}&format=json"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            return data[0] if data else None
        except (requests.RequestException, KeyError, IndexError):
            return None

    try:
        code = icao_code.upper().strip()

        # First, try the code as provided
        metar_data = fetch_metar_data(code)

        # If no data and it's a 3-letter code, try prepending "K"
        faa_code_length = 3
        if not metar_data and len(code) == faa_code_length:
            k_code = f"K{code}"
            metar_data = fetch_metar_data(k_code)
            if metar_data:
                code = k_code  # Update code for error messages

        if not metar_data:
            return f"No METAR data found for airport code: {icao_code}"

        # Extract basic info
        airport_name = metar_data.get("name", "Unknown Airport")
        raw_metar = metar_data.get("rawOb", "No raw observation available")

        # Build formatted response
        result = f"Airport: {airport_name}\n"
        result += f"Raw METAR: {raw_metar}\n\n"
        result += "Weather Data:\n"

        # Create table of non-null attributes (excluding specified fields)
        exclude_fields = {"name", "rawOb", "metar_id", "obsTime", "prior", "mostRecent"}
        for key, value in metar_data.items():
            if key not in exclude_fields and value is not None and value != "":
                result += f"  {key}: {value}\n"

    except Exception as e:  # noqa: BLE001
        return f"Error fetching METAR data: {e}"
    else:
        return result


def count_letters(text: str, letter: str) -> str:
    """Count occurrences of a specific letter in a text string.

    Args:
        text: The text to search in
        letter: The letter to count (case-insensitive)

    Returns:
        String describing the count result
    """
    if len(letter) != 1:
        return "Error: Please provide exactly one letter to count"

    # Convert to lowercase for case-insensitive counting
    text_lower = text.lower()
    letter_lower = letter.lower()

    count = text_lower.count(letter_lower)

    return f"The letter '{letter}' appears {count} times in '{text}'"


def websearch(query: str, limit: int = 10) -> str:
    """Search the web using a local SearXNG instance.

    Args:
        query: Search query string
        limit: Maximum number of results to return (default: 10)

    Returns:
        Formatted string with search results
    """
    # Get SearXNG URL from tool configuration
    searxng_url = _tool_config["searxng_url"]

    # Ensure limit is an integer (tool calls may pass it as string)
    limit = int(limit)

    params = {"q": query, "format": "json"}
    headers = {"User-Agent": "LLMBot/1.0"}

    try:
        response = requests.get(searxng_url, params=params, headers=headers, timeout=30)
        response.raise_for_status()
        results = response.json()

        formatted_results = [
            {
                "title": result["title"],
                "url": result["url"],
                "snippet": result.get("content", "No snippet available"),
            }
            for result in results.get("results", [])[:limit]
        ]

        if not formatted_results:
            return f"No search results found for query: {query}"

        # Format results as a readable string
        output = f"Search results for '{query}':\n\n"
        for i, item in enumerate(formatted_results, 1):
            output += f"{i}. {item['title']}\n"
            output += f"   URL: {item['url']}\n"
            output += f"   {item['snippet']}\n\n"

        return output.strip()

    except requests.RequestException as e:
        return f"Error performing web search: {e!s}"


# Define tools in Ollama format
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "add_numbers",
            "description": "Add two numbers together",
            "parameters": {
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
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "Get the current date and time",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_metar",
            "description": "Get METAR weather data for an airport by ICAO code",
            "parameters": {
                "type": "object",
                "properties": {
                    "icao_code": {
                        "type": "string",
                        "description": "3 or 4-letter airport code (e.g., GTU, KJFK)",
                    },
                },
                "required": ["icao_code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "subtract_numbers",
            "description": "Subtract two numbers",
            "parameters": {
                "type": "object",
                "properties": {
                    "a": {
                        "type": "number",
                        "description": "First number (minuend)",
                    },
                    "b": {
                        "type": "number",
                        "description": "Second number (subtrahend)",
                    },
                },
                "required": ["a", "b"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "multiply_numbers",
            "description": "Multiply two numbers",
            "parameters": {
                "type": "object",
                "properties": {
                    "a": {
                        "type": "number",
                        "description": "First number",
                    },
                    "b": {
                        "type": "number",
                        "description": "Second number",
                    },
                },
                "required": ["a", "b"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "divide_numbers",
            "description": "Divide two numbers",
            "parameters": {
                "type": "object",
                "properties": {
                    "a": {
                        "type": "number",
                        "description": "First number (dividend)",
                    },
                    "b": {
                        "type": "number",
                        "description": "Second number (divisor)",
                    },
                },
                "required": ["a", "b"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "count_letters",
            "description": "Count occurrences of a specific letter in a text string",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The text to search in",
                    },
                    "letter": {
                        "type": "string",
                        "description": "The letter to count (single character)",
                    },
                },
                "required": ["text", "letter"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "websearch",
            "description": "Search the web using a local SearXNG instance",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query string",
                    },
                    "limit": {
                        "type": "integer",
                        "description": (
                            "Maximum number of results to return (default: 10)"
                        ),
                        "default": 10,
                    },
                },
                "required": ["query"],
            },
        },
    },
]

# Tool registry for easy lookup
TOOL_FUNCTIONS: dict[str, Callable[..., Any]] = {
    "add_numbers": add_numbers,
    "subtract_numbers": subtract_numbers,
    "multiply_numbers": multiply_numbers,
    "divide_numbers": divide_numbers,
    "get_current_time": get_current_time,
    "get_metar": get_metar,
    "count_letters": count_letters,
    "websearch": websearch,
}


def call_tool(tool_name: str, arguments: dict[str, Any]) -> str:
    """Call a tool by name with arguments.

    Args:
        tool_name: Name of the tool to call
        arguments: Arguments to pass to the tool

    Returns:
        String result from the tool
    """
    if tool_name not in TOOL_FUNCTIONS:
        return f"Unknown tool: {tool_name}"

    try:
        logger.info("Calling tool: %s with args: %s", tool_name, arguments)
        func = TOOL_FUNCTIONS[tool_name]
        result = func(**arguments)
        logger.info("Tool result: %s", result)
        return str(result)
    except Exception as e:
        error_msg = f"Error calling tool {tool_name}: {e}"
        logger.exception(error_msg)
        return error_msg


def chat_with_tools(
    messages: list[dict[str, str]],
    ollama_client: ollama.Client,
    model: str,
    **ollama_options: Any,  # noqa: ANN401
) -> tuple[str, list[dict[str, str]]]:
    """Chat with Ollama using built-in tools.

    Args:
        messages: List of message dictionaries for conversation
        ollama_client: Ollama client instance
        model: Model name to use
        **ollama_options: Additional options to pass to Ollama

    Returns:
        Tuple of (final response text, complete conversation with tool calls)
    """
    if not TOOLS:
        # No tools available, use regular chat
        logger.info("No tools available, using regular chat")
        result = ollama_client.chat(model=model, messages=messages, **ollama_options)
        response_text = (
            result["message"]["content"] if result else "No response received"
        )
        return response_text, messages

    logger.info("Sending message to Ollama with %d tools available", len(TOOLS))

    # Send message to Ollama with available tools
    response = ollama_client.chat(
        model=model, messages=messages, tools=TOOLS, **ollama_options
    )

    # Check if model wants to use tools
    if response["message"].get("tool_calls"):
        logger.info(
            "Model requested %d tool calls", len(response["message"]["tool_calls"])
        )

        conversation = messages.copy()
        conversation.append(response["message"])

        # Execute each tool call
        for tool_call in response["message"]["tool_calls"]:
            function_name = tool_call["function"]["name"]
            function_args = tool_call["function"]["arguments"]

            logger.info("Executing tool call: %s(%s)", function_name, function_args)

            # Call the tool
            tool_result = call_tool(function_name, function_args)

            # Add tool result to conversation with proper format
            tool_response = {"role": "tool", "content": str(tool_result)}

            # Include tool_call_id if present (required by some models)
            if "id" in tool_call:
                tool_response["tool_call_id"] = tool_call["id"]

            conversation.append(tool_response)

        # Get final response from Ollama with tool results
        logger.info("Sending conversation with tool results: %s", conversation)
        final_response = ollama_client.chat(
            model=model, messages=conversation, **ollama_options
        )

        final_response_text = (
            final_response["message"]["content"]
            if final_response
            else "No response received"
        )
        return final_response_text, conversation
    # No tools called, return original response
    response_text = (
        response["message"]["content"] if response else "No response received"
    )
    return response_text, messages
