"""
Base PDF parser abstract class for bank statement PDFs.
"""
from abc import ABC, abstractmethod
from typing import List, Optional
from dataclasses import dataclass
from datetime import datetime

# Reuse ParsedTransaction from base_parser
from .base_parser import ParsedTransaction


class PDFParser(ABC):
    """
    Abstract base class for PDF bank statement parsers.

    Each bank implements a parser by extending this class and implementing:
    - get_name(): Unique identifier (e.g., "chase_bank_pdf")
    - get_display_name(): User-friendly name (e.g., "Chase Bank PDF")
    - detect(pdf_bytes): Returns confidence score 0.0-1.0
    - parse(pdf_bytes): Returns list of ParsedTransaction objects
    """

    @abstractmethod
    def get_name(self) -> str:
        """
        Get unique parser identifier.

        Returns:
            str: Unique parser name (e.g., "chase_bank_pdf")
        """
        pass

    @abstractmethod
    def get_display_name(self) -> str:
        """
        Get user-friendly display name.

        Returns:
            str: Display name (e.g., "Chase Bank PDF Statement")
        """
        pass

    def get_parser_type(self) -> str:
        """
        Get parser type (always 'pdf' for PDF parsers).

        Returns:
            str: 'pdf'
        """
        return "pdf"

    def get_required_headers(self) -> List[str]:
        """
        Get required headers (not applicable for PDF parsers).

        Returns:
            List[str]: Empty list (PDFs don't have CSV-style headers)
        """
        return []

    @abstractmethod
    def detect(self, pdf_bytes: bytes) -> float:
        """
        Detect if this parser can handle the given PDF.

        Args:
            pdf_bytes: Raw PDF file bytes

        Returns:
            float: Confidence score 0.0-1.0
                   0.0 = cannot parse
                   1.0 = perfect match
        """
        pass

    @abstractmethod
    def parse(self, pdf_bytes: bytes, account_type: Optional[str] = None) -> List[ParsedTransaction]:
        """
        Parse PDF into standardized transactions.

        Args:
            pdf_bytes: Raw PDF file bytes
            account_type: Account type for intelligent classification

        Returns:
            List[ParsedTransaction]: List of parsed transactions

        Raises:
            ValueError: If PDF cannot be parsed
        """
        pass
