"""
Base parser class and common structures for CSV import.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import List, Optional, Dict


@dataclass
class ParsedTransaction:
    """
    Standardized transaction output from all parsers.
    """
    date: datetime
    amount: Decimal
    description: str
    transaction_type: str  # 'income', 'expense', 'transfer'
    category: Optional[str] = None
    notes: Optional[str] = None
    raw_data: Dict = field(default_factory=dict)  # Original CSV row
    transfer_account_identifier: Optional[str] = None
    original_amount: Optional[Decimal] = None  # Original signed amount from CSV (preserves +/- as-is)


class CSVParser(ABC):
    """
    Abstract base class for all CSV parsers.

    Each parser implementation must:
    1. Identify itself with a unique name
    2. Detect if a CSV file matches its format
    3. Parse the CSV into standardized ParsedTransaction objects
    4. Declare required headers for validation
    """

    @abstractmethod
    def get_name(self) -> str:
        """
        Return unique parser identifier (e.g., 'amex', 'chase_credit').

        Returns:
            str: Parser name
        """
        pass

    @abstractmethod
    def get_display_name(self) -> str:
        """
        Return human-readable parser name (e.g., 'American Express', 'Chase Credit Card').

        Returns:
            str: Display name for UI
        """
        pass

    @abstractmethod
    def detect(self, csv_content: str) -> float:
        """
        Analyze CSV content and return confidence score that it matches this parser's format.

        Args:
            csv_content: Raw CSV file content as string

        Returns:
            float: Confidence score between 0.0 (no match) and 1.0 (perfect match)
        """
        pass

    @abstractmethod
    def parse(self, csv_content: str, account_type: Optional[str] = None) -> List[ParsedTransaction]:
        """
        Parse CSV content into list of standardized transactions.

        Args:
            csv_content: Raw CSV file content as string
            account_type: Account type (e.g., 'credit_card', 'checking', 'savings')
                         Used to intelligently classify transactions

        Returns:
            List[ParsedTransaction]: Parsed transactions

        Raises:
            ValueError: If CSV format is invalid or parsing fails
        """
        pass

    @abstractmethod
    def get_required_headers(self) -> List[str]:
        """
        Return list of required CSV headers for this parser.

        Returns:
            List[str]: Required header names
        """
        pass

    def get_parser_type(self) -> str:
        """
        Return parser category type ('credit_card' or 'bank_account').

        Returns:
            str: Parser type
        """
        return "credit_card"  # Default, override in bank parsers
