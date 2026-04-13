"""Test suite for llmbot tools."""
# ruff: noqa: S101, ANN201, D400, PLR2004, E402, ERA001, PGH003
# type: ignore

import re
import sys
import time
from unittest.mock import Mock

# Mock the ollama and requests modules to avoid import issues in tests
import pytest

sys.modules["ollama"] = Mock()
sys.modules["requests"] = Mock()
sys.modules["caldav"] = Mock()
sys.modules["icalendar"] = Mock()

from llmbot.tools import (
    add_numbers,
    count_letters,
    divide_numbers,
    get_current_time,
    get_taf,
    multiply_numbers,
    subtract_numbers,
)


class TestAddNumbers:
    """Test cases for the add_numbers function."""

    def test_whole_number_result_returns_int(self):
        """Test that whole number results return int type without .0"""
        result = add_numbers(5, 7)
        assert result == 12
        assert isinstance(result, int)

    def test_decimal_result_returns_float(self):
        """Test that decimal results return float type with decimals preserved"""
        result = add_numbers(2.5, 1.3)
        assert result == 3.8
        assert isinstance(result, float)

    def test_mixed_inputs_whole_result(self):
        """Test mixed int/float inputs that result in whole number"""
        result = add_numbers(2.5, 1.5)
        assert result == 4
        assert isinstance(result, int)

    def test_string_inputs_numeric(self):
        """Test that string inputs are converted to numbers correctly"""
        result = add_numbers("5", "7")
        assert result == 12
        assert isinstance(result, int)

    def test_string_inputs_decimal(self):
        """Test that string decimal inputs work correctly"""
        result = add_numbers("2.5", "1.3")
        assert result == 3.8
        assert isinstance(result, float)

    def test_mixed_string_and_number(self):
        """Test mixed string and number inputs"""
        result = add_numbers("5", 7)
        assert result == 12
        assert isinstance(result, int)

        result = add_numbers(2.5, "1.5")
        assert result == 4
        assert isinstance(result, int)

    def test_negative_numbers(self):
        """Test addition with negative numbers"""
        result = add_numbers(-5, 3)
        assert result == -2
        assert isinstance(result, int)

        result = add_numbers(-2.5, 1.2)
        assert result == -1.3
        assert isinstance(result, float)

    def test_zero_handling(self):
        """Test addition with zero"""
        result = add_numbers(0, 5)
        assert result == 5
        assert isinstance(result, int)

        result = add_numbers(0.0, 5.5)
        assert result == 5.5
        assert isinstance(result, float)

    def test_floating_point_precision(self):
        """Test floating point arithmetic edge cases"""
        result = add_numbers(0.1, 0.2)
        # Note: 0.1 + 0.2 = 0.30000000000000004 in Python
        assert abs(result - 0.3) < 1e-10
        assert isinstance(result, float)

    def test_large_numbers(self):
        """Test addition with large numbers"""
        result = add_numbers(1e10, 1e10)
        assert result == 2e10
        # Large numbers that result in whole numbers will be integers due to our logic
        assert isinstance(result, int)

    def test_invalid_string_inputs(self):
        """Test that invalid string inputs raise ValueError"""
        with pytest.raises(ValueError, match="Invalid number format"):
            add_numbers("abc", "5")

        with pytest.raises(ValueError, match="Invalid number format"):
            add_numbers("5", "xyz")

        with pytest.raises(ValueError, match="Invalid number format"):
            add_numbers("", "5")

    def test_none_inputs(self):
        """Test that None inputs raise ValueError"""
        with pytest.raises(ValueError, match="Invalid number format"):
            add_numbers(None, 5)

        with pytest.raises(ValueError, match="Invalid number format"):
            add_numbers(5, None)


class TestCountLetters:
    """Test cases for the count_letters function."""

    def test_count_letters_basic(self):
        """Test basic letter counting functionality"""
        result = count_letters("strawberry", "r")
        assert result == "The letter 'r' appears 3 times in 'strawberry'"

    def test_count_letters_case_insensitive(self):
        """Test that letter counting is case insensitive"""
        result = count_letters("Banana", "a")
        assert result == "The letter 'a' appears 3 times in 'Banana'"

        result = count_letters("banana", "A")
        assert result == "The letter 'A' appears 3 times in 'banana'"

    def test_count_letters_no_matches(self):
        """Test counting when letter doesn't exist"""
        result = count_letters("hello", "z")
        assert result == "The letter 'z' appears 0 times in 'hello'"

    def test_count_letters_empty_string(self):
        """Test counting in empty string"""
        result = count_letters("", "a")
        assert result == "The letter 'a' appears 0 times in ''"

    def test_count_letters_multiple_characters_error(self):
        """Test that multiple character input returns error"""
        result = count_letters("hello", "ab")
        assert result == "Error: Please provide exactly one letter to count"

    def test_count_letters_empty_letter_error(self):
        """Test that empty letter input returns error"""
        result = count_letters("hello", "")
        assert result == "Error: Please provide exactly one letter to count"


class TestSubtractNumbers:
    """Test cases for the subtract_numbers function."""

    def test_basic_subtraction(self):
        """Test basic subtraction returning integer"""
        result = subtract_numbers(10, 3)
        assert result == 7
        assert isinstance(result, int)

    def test_decimal_subtraction(self):
        """Test subtraction with decimal result"""
        result = subtract_numbers(5.5, 2.2)
        assert abs(result - 3.3) < 1e-10  # Handle floating point precision
        assert isinstance(result, float)

    def test_negative_result(self):
        """Test subtraction resulting in negative number"""
        result = subtract_numbers(3, 8)
        assert result == -5
        assert isinstance(result, int)

    def test_string_inputs(self):
        """Test subtraction with string inputs"""
        result = subtract_numbers("10", "3")
        assert result == 7
        assert isinstance(result, int)

    def test_zero_subtraction(self):
        """Test subtraction with zero"""
        result = subtract_numbers(5, 0)
        assert result == 5
        assert isinstance(result, int)

    def test_invalid_inputs(self):
        """Test that invalid inputs raise ValueError"""
        with pytest.raises(ValueError, match="Invalid number format"):
            subtract_numbers("abc", 5)


class TestMultiplyNumbers:
    """Test cases for the multiply_numbers function."""

    def test_basic_multiplication(self):
        """Test basic multiplication returning integer"""
        result = multiply_numbers(4, 3)
        assert result == 12
        assert isinstance(result, int)

    def test_decimal_multiplication(self):
        """Test multiplication with decimal result"""
        result = multiply_numbers(2.5, 1.5)
        assert result == 3.75
        assert isinstance(result, float)

    def test_multiplication_by_zero(self):
        """Test multiplication by zero"""
        result = multiply_numbers(5, 0)
        assert result == 0
        assert isinstance(result, int)

    def test_negative_multiplication(self):
        """Test multiplication with negative numbers"""
        result = multiply_numbers(-3, 4)
        assert result == -12
        assert isinstance(result, int)

        result = multiply_numbers(-2.5, -2)
        assert result == 5
        assert isinstance(result, int)

    def test_string_inputs(self):
        """Test multiplication with string inputs"""
        result = multiply_numbers("4", "3")
        assert result == 12
        assert isinstance(result, int)

    def test_invalid_inputs(self):
        """Test that invalid inputs raise ValueError"""
        with pytest.raises(ValueError, match="Invalid number format"):
            multiply_numbers("abc", 5)


class TestDivideNumbers:
    """Test cases for the divide_numbers function."""

    def test_basic_division(self):
        """Test basic division returning integer"""
        result = divide_numbers(12, 3)
        assert result == 4
        assert isinstance(result, int)

    def test_decimal_division(self):
        """Test division with decimal result"""
        result = divide_numbers(5, 2)
        assert result == 2.5
        assert isinstance(result, float)

    def test_division_by_one(self):
        """Test division by one"""
        result = divide_numbers(7, 1)
        assert result == 7
        assert isinstance(result, int)

    def test_division_resulting_in_fraction(self):
        """Test division resulting in decimal"""
        result = divide_numbers(7, 3)
        assert abs(result - 2.3333333333333335) < 1e-10
        assert isinstance(result, float)

    def test_string_inputs(self):
        """Test division with string inputs"""
        result = divide_numbers("12", "3")
        assert result == 4
        assert isinstance(result, int)

    def test_division_by_zero(self):
        """Test that division by zero raises ValueError"""
        with pytest.raises(ValueError, match="Division by zero is not allowed"):
            divide_numbers(5, 0)

        with pytest.raises(ValueError, match="Division by zero is not allowed"):
            divide_numbers(5, "0")

    def test_zero_divided_by_number(self):
        """Test zero divided by a number"""
        result = divide_numbers(0, 5)
        assert result == 0
        assert isinstance(result, int)

    def test_negative_division(self):
        """Test division with negative numbers"""
        result = divide_numbers(-12, 3)
        assert result == -4
        assert isinstance(result, int)

        result = divide_numbers(12, -3)
        assert result == -4
        assert isinstance(result, int)

    def test_invalid_inputs(self):
        """Test that invalid inputs raise ValueError"""
        with pytest.raises(ValueError, match="Invalid number format"):
            divide_numbers("abc", 5)


class TestGetTaf:
    """Test cases for the get_taf function."""

    def test_get_taf_success(self):
        """Test successful TAF fetch returns formatted output."""
        mock_requests = sys.modules["requests"]
        mock_response = Mock()
        mock_response.json.return_value = [
            {
                "icaoId": "KJFK",
                "name": "John F Kennedy Intl",
                "rawTAF": "KJFK 101730Z 1018/1124 27015KT P6SM FEW040",
                "issueTime": "2024-01-10T17:30:00Z",
                "validTimeFrom": "2024-01-10T18:00:00Z",
                "validTimeTo": "2024-01-11T24:00:00Z",
                "lat": 40.63,
                "lon": -73.78,
                "prior": 0,
                "mostRecent": 1,
                "dbPopTime": None,
                "bulletinTime": None,
                "fcsts": [
                    {
                        "timeFrom": "2024-01-10T18:00:00Z",
                        "timeTo": "2024-01-11T00:00:00Z",
                        "wdir": 270,
                        "wspd": 15,
                        "visib": 6.0,
                        "wxString": None,
                        "clouds": [{"cover": "FEW", "base": 4000}],
                    }
                ],
            }
        ]
        mock_response.raise_for_status = Mock()
        mock_requests.get.return_value = mock_response
        mock_requests.RequestException = Exception

        result = get_taf("KJFK")
        assert "John F Kennedy Intl" in result
        assert "KJFK 101730Z" in result
        assert "Forecast Periods:" in result
        assert "From:" in result

    def test_get_taf_no_data(self):
        """Test that empty response returns appropriate error message."""
        mock_requests = sys.modules["requests"]
        mock_response = Mock()
        mock_response.json.return_value = []
        mock_response.raise_for_status = Mock()
        mock_requests.get.return_value = mock_response
        mock_requests.RequestException = Exception

        result = get_taf("ZZZZ")
        assert "No TAF data found for airport code: ZZZZ" in result

    def test_get_taf_3letter_fallback(self):
        """Test that 3-letter codes fall back to K-prefix."""
        mock_requests = sys.modules["requests"]
        mock_requests.get.reset_mock()

        empty_response = Mock()
        empty_response.json.return_value = []
        empty_response.raise_for_status = Mock()

        full_response = Mock()
        full_response.json.return_value = [
            {
                "icaoId": "KGTU",
                "name": "Georgetown Municipal",
                "rawTAF": "KGTU 101730Z 1018/1118 VRB05KT P6SM SKC",
                "fcsts": [],
                "prior": 0,
                "mostRecent": 1,
                "dbPopTime": None,
                "bulletinTime": None,
            }
        ]
        full_response.raise_for_status = Mock()

        mock_requests.get.side_effect = [empty_response, full_response]
        mock_requests.RequestException = Exception

        result = get_taf("GTU")
        assert "Georgetown Municipal" in result
        assert mock_requests.get.call_count == 2

    def test_get_taf_request_error(self):
        """Test that network errors result in no-data message (caught in inner helper)."""
        mock_requests = sys.modules["requests"]
        mock_requests.RequestException = Exception
        mock_requests.get.side_effect = Exception("connection refused")

        result = get_taf("KJFK")
        # Exception is caught inside fetch_taf_data, returns None -> no data message
        assert "No TAF data found for airport code: KJFK" in result


class TestGetCurrentTime:
    """Test cases for the get_current_time function."""

    def test_get_current_time_format(self):
        """Test that current time returns properly formatted string"""
        result = get_current_time()
        assert isinstance(result, str)
        assert "UTC" in result
        # Basic format check: YYYY-MM-DD HH:MM:SS UTC
        pattern = r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC"
        assert re.match(pattern, result)

    def test_get_current_time_consistency(self):
        """Test that consecutive calls return similar timestamps"""
        time1 = get_current_time()
        time.sleep(0.1)  # Small delay
        time2 = get_current_time()

        # Both should be valid timestamps
        assert isinstance(time1, str)
        assert isinstance(time2, str)
        assert "UTC" in time1
        assert "UTC" in time2

        # They should be different (time has passed)
        # but have the same date (assuming test runs quickly)
        date1 = time1.split(" ")[0]
        date2 = time2.split(" ")[0]
        assert date1 == date2  # Same date
