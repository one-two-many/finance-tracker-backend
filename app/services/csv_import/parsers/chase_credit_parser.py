"""
Chase credit card CSV parser.
"""
import csv
from io import StringIO
from typing import List, Optional

from ..base_parser import CSVParser, ParsedTransaction
from ..utils import parse_date, parse_amount, calculate_header_confidence


class ChaseCreditParser(CSVParser):
    """
    Parser for Chase credit card CSV exports.

    Chase Credit CSV Format:
    - Transaction Date: MM/DD/YYYY
    - Post Date: MM/DD/YYYY
    - Description: Transaction description
    - Category: Chase category name
    - Type: Transaction type (Sale, Return, Payment, etc.)
    - Amount: Negative = expense, Positive = payment/credit
    """

    def get_name(self) -> str:
        return "chase_credit"

    def get_display_name(self) -> str:
        return "Chase Credit Card"

    def get_required_headers(self) -> List[str]:
        return ["Transaction Date", "Description", "Amount"]

    def detect(self, csv_content: str) -> float:
        """
        Detect Chase credit format by checking for specific headers.
        """
        required_headers = set(self.get_required_headers())
        confidence = calculate_header_confidence(csv_content, required_headers)

        # Boost confidence if Chase-specific optional headers are present
        try:
            csv_reader = csv.DictReader(StringIO(csv_content))
            headers = set(csv_reader.fieldnames or [])

            # Chase-specific headers
            chase_specific = {"Post Date", "Type", "Memo"}
            if chase_specific & headers:
                confidence = min(1.0, confidence + 0.2)

        except Exception:
            pass

        return confidence

    def parse(self, csv_content: str, account_type: Optional[str] = None) -> List[ParsedTransaction]:
        """
        Parse Chase credit CSV into standardized transactions.

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
                f"Invalid Chase CSV format. Expected headers: {required}. Found: {headers}"
            )

        for row in csv_reader:
            # Skip empty rows
            if not any(row.values()):
                continue

            # Extract fields
            date_str = row.get("Transaction Date", "").strip()
            description = row.get("Description", "").strip()
            amount_str = row.get("Amount", "").strip()
            category_name = row.get("Category", "").strip()
            transaction_type_str = row.get("Type", "").strip()
            memo = row.get("Memo", "").strip()

            # Validate required fields
            if not date_str or not description or not amount_str:
                continue

            try:
                # Parse date (MM/DD/YYYY)
                transaction_date = parse_date(date_str, "%m/%d/%Y")

                # Parse amount
                amount_value = parse_amount(amount_str)

                # Determine transaction type based on amount sign
                # Note: Chase uses negative for expenses, positive for payments/credits
                if amount_value < 0:
                    transaction_type = "expense"
                    amount_abs = abs(amount_value)
                else:
                    transaction_type = "income"
                    amount_abs = amount_value

                # Create notes from memo
                notes = memo if memo else None

                # Create parsed transaction
                transaction = ParsedTransaction(
                    date=transaction_date,
                    amount=amount_abs,
                    description=description,
                    transaction_type=transaction_type,
                    category=category_name if category_name else None,
                    notes=notes,
                    raw_data=dict(row),
                    original_amount=amount_value  # Preserve original signed amount from CSV
                )

                transactions.append(transaction)

            except (ValueError, Exception):
                # Skip rows with parsing errors
                continue

        return transactions
