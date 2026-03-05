"""
Discover Bank CSV parser.
"""
import csv
from io import StringIO
from typing import List, Optional

from ..base_parser import CSVParser, ParsedTransaction
from ..utils import parse_date, parse_amount, calculate_header_confidence


class DiscoverBankParser(CSVParser):
    """
    Parser for Discover Bank CSV exports.

    Discover Bank CSV Format:
    - Trans. Date: MM/DD/YYYY
    - Post Date: MM/DD/YYYY
    - Description: Transaction description
    - Amount: Positive = expense, Negative = credit/refund
    - Category: Discover category name
    """

    def get_name(self) -> str:
        return "discover_bank"

    def get_display_name(self) -> str:
        return "Discover Bank"

    def get_required_headers(self) -> List[str]:
        return ["Trans. Date", "Description", "Amount"]

    def get_parser_type(self) -> str:
        """Discover can be used for both cards and bank accounts."""
        return "bank_account"

    # Keywords for detecting different transaction types
    TRANSFER_KEYWORDS = [
        "transfer", "payment", "zelle", "venmo", "ach", "wire",
        "online payment", "automatic payment"
    ]

    REFUND_KEYWORDS = [
        "refund", "return", "reversal", "chargeback"
    ]

    CASHBACK_KEYWORDS = [
        "cashback", "cash back", "rewards", "bonus"
    ]

    def detect(self, csv_content: str) -> float:
        """
        Detect Discover Bank format by checking for specific headers.
        """
        required_headers = set(self.get_required_headers())
        confidence = calculate_header_confidence(csv_content, required_headers)

        # Boost confidence if Discover-specific headers are present
        try:
            csv_reader = csv.DictReader(StringIO(csv_content))
            headers = set(csv_reader.fieldnames or [])

            # Discover-specific headers
            discover_specific = {"Trans. Date", "Post Date"}
            if discover_specific.issubset(headers):
                confidence = min(1.0, confidence + 0.2)

        except Exception:
            pass

        return confidence

    def parse(self, csv_content: str, account_type: Optional[str] = None) -> List[ParsedTransaction]:
        """
        Parse Discover Bank CSV into standardized transactions.

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
                f"Invalid Discover Bank CSV format. Expected headers: {required}. Found: {headers}"
            )

        for row in csv_reader:
            # Skip empty rows
            if not any(row.values()):
                continue

            # Extract fields
            date_str = row.get("Trans. Date", "").strip()
            description = row.get("Description", "").strip()
            amount_str = row.get("Amount", "").strip()
            category_name = row.get("Category", "").strip()

            # Validate required fields
            if not date_str or not description or not amount_str:
                continue

            try:
                # Parse date (MM/DD/YYYY)
                transaction_date = parse_date(date_str, "%m/%d/%Y")

                # Parse amount
                amount_value = parse_amount(amount_str)

                # Intelligently determine transaction type
                desc_lower = description.lower()

                # For bank/card accounts, classify based on keywords
                if amount_value > 0:
                    # Positive = debit/charge
                    # Could be expense OR transfer out
                    if any(kw in desc_lower for kw in self.TRANSFER_KEYWORDS):
                        transaction_type = "transfer"
                    else:
                        transaction_type = "expense"
                    amount_abs = amount_value
                else:
                    # Negative = credit/deposit
                    # Could be income, transfer in, refund, or cashback
                    amount_abs = abs(amount_value)

                    if any(kw in desc_lower for kw in self.TRANSFER_KEYWORDS):
                        transaction_type = "transfer"
                    elif any(kw in desc_lower for kw in self.REFUND_KEYWORDS):
                        transaction_type = "refund"
                    elif any(kw in desc_lower for kw in self.CASHBACK_KEYWORDS):
                        transaction_type = "income"
                    else:
                        transaction_type = "income"

                # Create parsed transaction
                transaction = ParsedTransaction(
                    date=transaction_date,
                    amount=amount_abs,
                    description=description,
                    transaction_type=transaction_type,
                    category=category_name if category_name else None,
                    notes=None,
                    raw_data=dict(row),
                    original_amount=amount_value  # Preserve original signed amount from CSV
                )

                transactions.append(transaction)

            except (ValueError, Exception):
                # Skip rows with parsing errors
                continue

        return transactions
