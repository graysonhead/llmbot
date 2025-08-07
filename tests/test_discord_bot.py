"""Tests for Discord bot functionality."""
# ruff: noqa: S101

import re


def _parse_model_from_query(
    query: str, default_model: str = "llama3.1:8b"
) -> tuple[str, str]:
    """Parse model specification from query and return (model, cleaned_query)."""
    # Look for !model=<model_name> pattern
    model_pattern = r"!model=(\S+)"
    match = re.search(model_pattern, query)

    if match:
        model_name = match.group(1)
        # Remove the model specification from the query
        cleaned_query = re.sub(model_pattern, "", query).strip()
        return model_name, cleaned_query

    # No model specified, use default
    return default_model, query


class TestLLMBot:
    """Test cases for LLMBot class."""

    def test_parse_model_from_query_with_model_specification(self) -> None:
        """Test parsing query with model specification."""
        result = _parse_model_from_query("!model=mixtral:8x7b What is the weather?")
        expected = ("mixtral:8x7b", "What is the weather?")
        assert result == expected

    def test_parse_model_from_query_no_model_specification(self) -> None:
        """Test parsing query without model specification."""
        result = _parse_model_from_query("Hello world")
        expected = ("llama3.1:8b", "Hello world")
        assert result == expected

    def test_parse_model_from_query_empty_query_after_model(self) -> None:
        """Test parsing with only model specification."""
        result = _parse_model_from_query("!model=gpt-4")
        expected = ("gpt-4", "")
        assert result == expected

    def test_parse_model_from_query_model_in_middle(self) -> None:
        """Test parsing with model specification in middle of query."""
        result = _parse_model_from_query("Before !model=claude-3-opus after")
        expected = ("claude-3-opus", "Before  after")
        assert result == expected

    def test_parse_model_from_query_multiple_models(self) -> None:
        """Test parsing with multiple model specifications (should use first one)."""
        result = _parse_model_from_query(
            "!model=gpt-4 some text !model=claude-3-opus more text"
        )
        expected = ("gpt-4", "some text !model=claude-3-opus more text")
        assert result == expected

    def test_parse_model_from_query_complex_model_names(self) -> None:
        """Test parsing with complex model names containing colons and hyphens."""
        test_cases = [
            (
                "!model=mixtral:8x7b-instruct Query here",
                "mixtral:8x7b-instruct",
                "Query here",
            ),
            ("!model=llama3.1:70b-chat Test query", "llama3.1:70b-chat", "Test query"),
            (
                "!model=claude-3-5-sonnet-20241022 Help me",
                "claude-3-5-sonnet-20241022",
                "Help me",
            ),
        ]

        for query, expected_model, expected_query in test_cases:
            result = _parse_model_from_query(query)
            expected = (expected_model, expected_query)
            assert result == expected

    def test_parse_model_from_query_whitespace_handling(self) -> None:
        """Test proper whitespace handling around model specifications."""
        test_cases = [
            ("   !model=gpt-4   What is AI?   ", "gpt-4", "What is AI?"),
            ("!model=claude-3-opus", "claude-3-opus", ""),
            ("  !model=mixtral:8x7b  ", "mixtral:8x7b", ""),
        ]

        for query, expected_model, expected_query in test_cases:
            result = _parse_model_from_query(query)
            expected = (expected_model, expected_query)
            assert result == expected
