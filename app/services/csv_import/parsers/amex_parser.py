"""
American Express credit card CSV parser.
"""
import csv
from io import StringIO
from typing import List, Optional
from decimal import Decimal

from ..base_parser import CSVParser, ParsedTransaction
from ..utils import parse_date, parse_amount, calculate_header_confidence


class AmexParser(CSVParser):
    """
    Parser for American Express credit card CSV exports.

    AMEX CSV Format:
    - Date: MM/DD/YYYY
    - Description: Transaction description
    - Amount: Positive = expense, Negative = income/payment
    - Appears On Your Statement As: Additional info (optional)
    - Category: AMEX category name (optional)
    """

    def get_name(self) -> str:
        return "amex"

    def get_display_name(self) -> str:
        return "American Express"

    def get_required_headers(self) -> List[str]:
        return ["Date", "Description", "Amount"]

    def detect(self, csv_content: str) -> float:
        """
        Detect AMEX format by checking for specific headers.

        Returns higher confidence if optional AMEX-specific headers are present.
        """
        required_headers = set(self.get_required_headers())
        confidence = calculate_header_confidence(csv_content, required_headers)

        # Boost confidence if AMEX-specific optional headers are present
        try:
            csv_reader = csv.DictReader(StringIO(csv_content))
            headers = set(csv_reader.fieldnames or [])

            # AMEX-specific headers
            amex_specific = {"Appears On Your Statement As", "Category", "Card Member"}
            if amex_specific & headers:
                confidence = min(1.0, confidence + 0.2)

        except Exception:
            pass

        return confidence

    # Keywords for detecting different transaction types
    TRANSFER_KEYWORDS = [
        "payment", "online payment", "automatic payment", "autopay",
        "thank you", "payment received", "credit card payment"
    ]

    REFUND_KEYWORDS = [
        "refund", "return", "reversal", "chargeback", "credit adjustment"
    ]

    CASHBACK_KEYWORDS = [
        "cashback", "cash back", "rewards", "reward credit", "points credit",
        "statement credit", "promotional credit", "membership rewards"
    ]

    def parse(self, csv_content: str, account_type: Optional[str] = None) -> List[ParsedTransaction]:
        """
        Parse AMEX CSV into standardized transactions.

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
                f"Invalid AMEX CSV format. Expected headers: {required}. Found: {headers}"
            )

        for row in csv_reader:
            # Skip empty rows
            if not any(row.values()):
                continue

            # Extract fields
            date_str = row.get("Date", "").strip()
            description = row.get("Description", "").strip()
            amount_str = row.get("Amount", "").strip()
            statement_as = row.get("Appears On Your Statement As", "").strip()
            category_name = row.get("Category", "").strip()

            # Validate required fields
            if not date_str or not description or not amount_str:
                continue  # Skip invalid rows

            try:
                # Parse date (MM/DD/YYYY)
                transaction_date = parse_date(date_str, "%m/%d/%Y")

                # Parse amount
                amount_value = parse_amount(amount_str)

                # Determine transaction type intelligently
                # For credit cards:
                # - Positive amount = charge/purchase = EXPENSE
                # - Negative amount could be:
                #   1. Payment (transfer from bank) = TRANSFER
                #   2. Refund (reversal of charge) = EXPENSE (negative)
                #   3. Cashback/rewards = keep as INCOME

                desc_lower = description.lower()

                if amount_value >= 0:
                    # Positive = charge/purchase
                    transaction_type = "expense"
                    amount_abs = amount_value
                else:
                    # Negative amount - need to classify intelligently
                    amount_abs = abs(amount_value)

                    # Check if it's a payment (transfer)
                    if any(kw in desc_lower for kw in self.TRANSFER_KEYWORDS):
                        transaction_type = "transfer"
                    # Check if it's a refund (should offset expenses)
                    elif any(kw in desc_lower for kw in self.REFUND_KEYWORDS):
                        transaction_type = "refund"  # Special marker
                    # Check if it's cashback/rewards
                    elif any(kw in desc_lower for kw in self.CASHBACK_KEYWORDS):
                        transaction_type = "income"  # Keep as income
                    else:
                        # Default: treat as income (safer than assuming transfer)
                        transaction_type = "income"

                # Create notes from statement_as
                notes = statement_as if statement_as else None

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

            except (ValueError, Exception) as e:
                # Skip rows with parsing errors
                continue

        return transactions
