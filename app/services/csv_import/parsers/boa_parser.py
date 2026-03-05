"""
Bank of America checking/savings account CSV parser.
"""
import csv
from io import StringIO
from typing import List, Optional

from ..base_parser import CSVParser, ParsedTransaction
from ..utils import parse_date, parse_amount, calculate_header_confidence


class BofAParser(CSVParser):
    """
    Parser for Bank of America CSV exports.

    BofA CSV Format:
    - Date: MM/DD/YYYY
    - Description: Transaction description
    - Amount: Transaction amount (negative or positive)
    - Running Bal.: Account balance
    """

    def get_name(self) -> str:
        return "bofa"

    def get_display_name(self) -> str:
        return "Bank of America"

    def get_parser_type(self) -> str:
        return "bank_account"

    def get_required_headers(self) -> List[str]:
        return ["Date", "Description", "Amount"]

    def detect(self, csv_content: str) -> float:
        """
        Detect Bank of America format by checking for specific headers.
        """
        required_headers = set(self.get_required_headers())
        confidence = calculate_header_confidence(csv_content, required_headers)

        # Boost confidence if BofA-specific headers are present
        try:
            csv_reader = csv.DictReader(StringIO(csv_content))
            headers = set(csv_reader.fieldnames or [])

            # BofA specific header
            if "Running Bal." in headers:
                confidence = min(1.0, confidence + 0.3)

        except Exception:
            pass

        return confidence

    def parse(self, csv_content: str, account_type: Optional[str] = None) -> List[ParsedTransaction]:
        """
        Parse Bank of America CSV into standardized transactions.

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
                f"Invalid Bank of America CSV format. Expected headers: {required}. Found: {headers}"
            )

        for row in csv_reader:
            # Skip empty rows
            if not any(row.values()):
                continue

            # Extract fields
            date_str = row.get("Date", "").strip()
            description = row.get("Description", "").strip()
            amount_str = row.get("Amount", "").strip()

            # Validate required fields
            if not date_str or not description or not amount_str:
                continue

            try:
                # Parse date (MM/DD/YYYY)
                transaction_date = parse_date(date_str, "%m/%d/%Y")

                # Parse amount
                amount_value = parse_amount(amount_str)

                # Determine transaction type
                # Positive = income (deposits), Negative = expense (withdrawals)
                if amount_value > 0:
                    transaction_type = "income"
                    amount_abs = amount_value
                else:
                    transaction_type = "expense"
                    amount_abs = abs(amount_value)

                # Check for transfer keywords
                transfer_identifier = None
                transfer_keywords = ["transfer", "zelle", "online banking transfer"]
                desc_lower = description.lower()
                if any(keyword in desc_lower for keyword in transfer_keywords):
                    transfer_identifier = description

                # Create parsed transaction
                transaction = ParsedTransaction(
                    date=transaction_date,
                    amount=amount_abs,
                    description=description,
                    transaction_type=transaction_type,
                    transfer_account_identifier=transfer_identifier,
                    raw_data=dict(row),
                    original_amount=amount_value  # Preserve original signed amount from CSV
                )

                transactions.append(transaction)

            except (ValueError, Exception):
                # Skip rows with parsing errors
                continue

        return transactions
