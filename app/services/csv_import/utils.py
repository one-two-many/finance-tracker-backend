"""
Utility functions for CSV parsing shared across all parsers.
"""
import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation
from io import StringIO
from typing import List, Set


def parse_date(date_str: str, format_str: str) -> datetime:
    """
    Parse date string with specified format.

    Args:
        date_str: Date string to parse
        format_str: Python datetime format string (e.g., '%m/%d/%Y')

    Returns:
        datetime: Parsed datetime object

    Raises:
        ValueError: If date format is invalid
    """
    return datetime.strptime(date_str.strip(), format_str)


def parse_amount(amount_str: str) -> Decimal:
    """
    Parse amount string to Decimal, removing currency symbols and commas.

    Args:
        amount_str: Amount string (e.g., '$1,234.56', '(100.00)', '-50.25')

    Returns:
        Decimal: Parsed amount

    Raises:
        ValueError: If amount cannot be parsed
    """
    try:
        # Remove currency symbols, commas, and extra spaces
        cleaned = amount_str.strip()
        cleaned = cleaned.replace("$", "").replace(",", "").replace(" ", "")

        # Handle parentheses as negative (accounting format)
        if cleaned.startswith("(") and cleaned.endswith(")"):
            cleaned = "-" + cleaned[1:-1]

        return Decimal(cleaned)
    except (InvalidOperation, ValueError) as e:
        raise ValueError(f"Invalid amount format: {amount_str}") from e


def get_csv_headers(csv_content: str) -> Set[str]:
    """
    Extract header row from CSV content.

    Args:
        csv_content: Raw CSV file content

    Returns:
        Set[str]: Set of header names

    Raises:
        ValueError: If CSV is invalid or empty
    """
    try:
        csv_reader = csv.DictReader(StringIO(csv_content))
        if csv_reader.fieldnames is None:
            raise ValueError("CSV file is empty or has no headers")
        return set(csv_reader.fieldnames)
    except Exception as e:
        raise ValueError(f"Failed to read CSV headers: {str(e)}") from e


def validate_headers(csv_content: str, required_headers: Set[str]) -> bool:
    """
    Check if CSV contains all required headers.

    Args:
        csv_content: Raw CSV file content
        required_headers: Set of required header names

    Returns:
        bool: True if all required headers present, False otherwise
    """
    try:
        actual_headers = get_csv_headers(csv_content)
        return required_headers.issubset(actual_headers)
    except Exception:
        return False


def calculate_header_confidence(csv_content: str, expected_headers: Set[str]) -> float:
    """
    Calculate confidence score based on header matching.

    Args:
        csv_content: Raw CSV file content
        expected_headers: Set of expected header names

    Returns:
        float: Confidence score 0.0-1.0 based on percentage of matching headers
    """
    try:
        actual_headers = get_csv_headers(csv_content)

        # If no expected headers, return 0
        if not expected_headers:
            return 0.0

        # Calculate match percentage
        matches = len(expected_headers & actual_headers)
        return matches / len(expected_headers)

    except Exception:
        return 0.0
