"""
Citi credit card CSV parser.
"""
import csv
from io import StringIO
from typing import List, Optional

from ..base_parser import CSVParser, ParsedTransaction
from ..utils import parse_date, parse_amount, calculate_header_confidence


class CitiParser(CSVParser):
    """
    Parser for Citi credit card CSV exports.

    Citi CSV Format:
    - Status: Cleared/Pending
    - Date: MM/DD/YYYY
    - Description: Transaction description
    - Debit: Expense amount (if applicable)
    - Credit: Credit/payment amount (if applicable)
    """

    def get_name(self) -> str:
        return "citi"

    def get_display_name(self) -> str:
        return "Citi Credit Card"

    def get_required_headers(self) -> List[str]:
        return ["Date", "Description"]

    def detect(self, csv_content: str) -> float:
        """
        Detect Citi format by checking for specific headers.
        """
        required_headers = set(self.get_required_headers())
        confidence = calculate_header_confidence(csv_content, required_headers)

        # Boost confidence if Citi-specific headers are present
        try:
            csv_reader = csv.DictReader(StringIO(csv_content))
            headers = set(csv_reader.fieldnames or [])

            # Citi uses Debit/Credit columns instead of single Amount
            if {"Debit", "Credit"}.issubset(headers):
                confidence = min(1.0, confidence + 0.3)

            if "Status" in headers:
                confidence = min(1.0, confidence + 0.1)

        except Exception:
            pass

        return confidence

    def parse(self, csv_content: str, account_type: Optional[str] = None) -> List[ParsedTransaction]:
        """
        Parse Citi CSV into standardized transactions.

        Args:
            csv_content: Raw CSV content
            account_type: Account type for intelligent classification
        """
        transactions = []
        csv_reader = csv.DictReader(StringIO(csv_content))

        # Validate headers
        if not csv_reader.fieldnames:
            raise ValueError("CSV file is empty or has no headers")

        headers = set(csv_reader.fieldnames)
        required = set(self.get_required_headers())

        if not required.issubset(headers):
            raise ValueError(
                f"Invalid Citi CSV format. Expected headers: {required}. Found: {headers}"
            )

        for row in csv_reader:
            # Skip empty rows
            if not any(row.values()):
                continue

            # Extract fields
            date_str = row.get("Date", "").strip()
            description = row.get("Description", "").strip()
            debit_str = row.get("Debit", "").strip()
            credit_str = row.get("Credit", "").strip()
            status = row.get("Status", "").strip()

            # Validate required fields
            if not date_str or not description:
                continue

            # Must have either debit or credit
            if not debit_str and not credit_str:
                continue

            try:
                # Parse date (MM/DD/YYYY)
                transaction_date = parse_date(date_str, "%m/%d/%Y")

                # Determine amount and type
                if debit_str:
                    amount = parse_amount(debit_str)
                    transaction_type = "expense"
                else:
                    amount = parse_amount(credit_str)
                    transaction_type = "income"

                # Create notes from status
                notes = f"Status: {status}" if status else None

                # Create parsed transaction
                transaction = ParsedTransaction(
                    date=transaction_date,
                    amount=amount,
                    description=description,
                    transaction_type=transaction_type,
                    notes=notes,
                    raw_data=dict(row),
                    original_amount=amount_value  # Preserve original signed amount from CSV
                )

                transactions.append(transaction)

            except (ValueError, Exception):
                # Skip rows with parsing errors
                continue

        return transactions
