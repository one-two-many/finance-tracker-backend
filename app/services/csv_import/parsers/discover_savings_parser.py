"""
Discover Bank Savings Account CSV parser.
"""
import csv
from io import StringIO
from typing import List, Optional

from ..base_parser import CSVParser, ParsedTransaction
from ..utils import parse_date, calculate_header_confidence


def _parse_discover_amount(value: str) -> float:
    """
    Parse a Discover Savings amount field.
    Values are either '0' or '$1,234.56'.
    Returns 0.0 if the field is zero/empty.
    """
    value = value.strip()
    if not value or value == "0":
        return 0.0
    # Remove leading $, commas, and any surrounding whitespace
    cleaned = value.replace("$", "").replace(",", "").strip()
    return float(cleaned)


class DiscoverSavingsParser(CSVParser):
    """
    Parser for Discover Bank Savings Account CSV exports.

    Discover Savings CSV Format:
    - Transaction Date: MM/DD/YYYY
    - Transaction Description: Description of the transaction
    - Transaction Type: 'Credit' (money in) or 'Debit' (money out)
    - Debit: dollar amount like $100.00, or 0 when not applicable
    - Credit: dollar amount like $79.14, or 0 when not applicable
    - Balance: running account balance
    """

    TRANSFER_KEYWORDS = [
        "transfer", "payment", "zelle", "venmo", "ach", "wire",
        "online payment", "automatic payment", "withdrawal", "deposit"
    ]

    REFUND_KEYWORDS = [
        "refund", "return", "reversal", "chargeback"
    ]

    def get_name(self) -> str:
        return "discover_savings"

    def get_display_name(self) -> str:
        return "Discover Savings"

    def get_required_headers(self) -> List[str]:
        return [
            "Transaction Date",
            "Transaction Description",
            "Transaction Type",
            "Debit",
            "Credit",
        ]

    def get_parser_type(self) -> str:
        return "bank_account"

    def detect(self, csv_content: str) -> float:
        """
        Detect Discover Savings format by checking for its distinctive headers.
        The combination of 'Transaction Type' + 'Debit' + 'Credit' columns (with
        'Balance') is unique to this format and distinguishes it from the Discover
        card parser which uses 'Trans. Date', 'Amount', and 'Category'.
        """
        required_headers = set(self.get_required_headers())
        confidence = calculate_header_confidence(csv_content, required_headers)

        try:
            csv_reader = csv.DictReader(StringIO(csv_content))
            headers = set(csv_reader.fieldnames or [])

            # 'Balance' column strongly suggests a bank/savings account statement
            if "Balance" in headers:
                confidence = min(1.0, confidence + 0.15)

            # Ensure we don't confuse with the Discover card format
            if "Trans. Date" in headers or "Category" in headers:
                confidence = max(0.0, confidence - 0.5)

        except Exception:
            pass

        return confidence

    def parse(self, csv_content: str, account_type: Optional[str] = None) -> List[ParsedTransaction]:
        """
        Parse Discover Savings CSV into standardized transactions.

        Args:
            csv_content: Raw CSV content
            account_type: Unused; savings accounts are always classified as bank_account
        """
        transactions = []
        csv_reader = csv.DictReader(StringIO(csv_content))

        if not csv_reader.fieldnames:
            raise ValueError("CSV file is empty or has no headers")

        headers = set(csv_reader.fieldnames)
        required = set(self.get_required_headers())

        if not required.issubset(headers):
            raise ValueError(
                f"Invalid Discover Savings CSV format. "
                f"Expected headers: {required}. Found: {headers}"
            )

        for row in csv_reader:
            if not any(row.values()):
                continue

            date_str = row.get("Transaction Date", "").strip()
            description = row.get("Transaction Description", "").strip()
            transaction_type_raw = row.get("Transaction Type", "").strip().lower()
            debit_str = row.get("Debit", "0").strip()
            credit_str = row.get("Credit", "0").strip()

            if not date_str or not description:
                continue

            try:
                transaction_date = parse_date(date_str, "%m/%d/%Y")

                debit_amount = _parse_discover_amount(debit_str)
                credit_amount = _parse_discover_amount(credit_str)

                # Use whichever column is non-zero; Debit = money out, Credit = money in
                if debit_amount > 0:
                    amount_abs = debit_amount
                    original_amount = -debit_amount  # negative = money leaving
                else:
                    amount_abs = credit_amount
                    original_amount = credit_amount   # positive = money coming in

                # Determine transaction type from description keywords and flow direction
                desc_lower = description.lower()

                if any(kw in desc_lower for kw in self.REFUND_KEYWORDS):
                    transaction_type = "refund"
                elif any(kw in desc_lower for kw in self.TRANSFER_KEYWORDS):
                    transaction_type = "transfer"
                elif transaction_type_raw == "credit":
                    # Money coming in that isn't a transfer — treat as income
                    # (e.g. interest payments)
                    transaction_type = "income"
                else:
                    # Debit = expense by default
                    transaction_type = "expense"

                transaction = ParsedTransaction(
                    date=transaction_date,
                    amount=amount_abs,
                    description=description,
                    transaction_type=transaction_type,
                    category=None,
                    notes=None,
                    raw_data=dict(row),
                    original_amount=original_amount,
                )

                transactions.append(transaction)

            except (ValueError, Exception):
                continue

        return transactions
