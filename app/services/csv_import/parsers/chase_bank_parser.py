"""
Chase checking/savings account CSV parser.
"""
import csv
from io import StringIO
from typing import List, Optional, Dict
from datetime import datetime

from ..base_parser import CSVParser, ParsedTransaction
from ..utils import parse_date, parse_amount, calculate_header_confidence


class ChaseBankParser(CSVParser):
    """
    Parser for Chase bank account CSV exports.

    Chase Bank CSV Format:
    - Details: Transaction type (DEBIT, CHECK, ACH_CREDIT, etc.)
    - Posting Date: MM/DD/YYYY
    - Description: Transaction description
    - Amount: Negative = withdrawal, Positive = deposit
    - Type: Transaction type
    - Balance: Account balance after transaction
    """

    def get_name(self) -> str:
        return "chase_bank"

    def get_display_name(self) -> str:
        return "Chase Checking/Savings"

    def get_parser_type(self) -> str:
        return "bank_account"

    def get_required_headers(self) -> List[str]:
        return ["Posting Date", "Description", "Amount"]

    # Keywords for detecting different transaction types
    TRANSFER_KEYWORDS = [
        "transfer", "payment", "zelle", "venmo", "ach", "wire",
        "online payment", "automatic payment", "credit card payment"
    ]

    REFUND_KEYWORDS = [
        "refund", "return", "reversal", "chargeback"
    ]

    CASHBACK_KEYWORDS = [
        "cashback", "cash back", "rewards", "bonus", "interest"
    ]

    def detect(self, csv_content: str) -> float:
        """
        Detect Chase bank format by checking for specific headers.
        """
        required_headers = set(self.get_required_headers())
        confidence = calculate_header_confidence(csv_content, required_headers)

        # Boost confidence if Chase bank-specific headers are present
        try:
            csv_reader = csv.DictReader(StringIO(csv_content))
            headers = set(csv_reader.fieldnames or [])

            # Chase bank specific headers
            chase_bank_specific = {"Details", "Type", "Balance"}
            if chase_bank_specific & headers:
                confidence = min(1.0, confidence + 0.3)

        except Exception:
            pass

        return confidence

    def parse(self, csv_content: str, account_type: Optional[str] = None) -> List[ParsedTransaction]:
        """
        Parse Chase bank CSV into standardized transactions.

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
                f"Invalid Chase bank CSV format. Expected headers: {required}. Found: {headers}"
            )

        for row in csv_reader:
            # Skip empty rows
            if not any(row.values()):
                continue

            # Extract fields
            date_str = row.get("Posting Date", "").strip()
            description = row.get("Description", "").strip()
            amount_str = row.get("Amount", "").strip()
            details = row.get("Details", "").strip()
            transaction_type_str = row.get("Type", "").strip()

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
                transfer_identifier = None

                if amount_value > 0:
                    # Positive = deposit/credit
                    amount_abs = amount_value

                    if any(kw in desc_lower for kw in self.TRANSFER_KEYWORDS):
                        transaction_type = "transfer"
                        transfer_identifier = description
                    elif any(kw in desc_lower for kw in self.REFUND_KEYWORDS):
                        transaction_type = "income"  # Refund to bank account is income
                    elif any(kw in desc_lower for kw in self.CASHBACK_KEYWORDS):
                        transaction_type = "income"
                    else:
                        transaction_type = "income"
                else:
                    # Negative = withdrawal/debit
                    amount_abs = abs(amount_value)

                    if any(kw in desc_lower for kw in self.TRANSFER_KEYWORDS):
                        transaction_type = "transfer"
                        transfer_identifier = description
                    else:
                        transaction_type = "expense"

                # Create notes from details
                notes = f"{details} - {transaction_type_str}" if details and transaction_type_str else None

                # Create parsed transaction
                transaction = ParsedTransaction(
                    date=transaction_date,
                    amount=amount_abs,
                    description=description,
                    transaction_type=transaction_type,
                    notes=notes,
                    transfer_account_identifier=transfer_identifier,
                    raw_data=dict(row),
                    original_amount=amount_value  # Preserve original signed amount from CSV
                )

                transactions.append(transaction)

            except (ValueError, Exception):
                # Skip rows with parsing errors
                continue

        return transactions

    def extract_balances(self, csv_content: str) -> Dict[str, Optional[float]]:
        """
        Extract start and end month balances from Chase CSV.

        The Balance column shows the account balance AFTER each transaction.
        We find the earliest and latest transactions to get start/end balances.

        Returns:
            dict with 'start_balance', 'end_balance', 'start_date', 'end_date'
        """
        try:
            csv_reader = csv.DictReader(StringIO(csv_content))

            balance_data = []
            for row in csv_reader:
                balance_str = row.get('Balance', '').strip()
                date_str = row.get('Posting Date', '').strip()

                if balance_str and date_str:
                    try:
                        balance = parse_amount(balance_str)
                        date = parse_date(date_str, "%m/%d/%Y")
                        balance_data.append((date, balance))
                    except (ValueError, Exception):
                        continue

            if not balance_data:
                return {
                    'start_balance': None,
                    'end_balance': None,
                    'start_date': None,
                    'end_date': None
                }

            # Sort by date (oldest first)
            balance_data.sort(key=lambda x: x[0])

            # Oldest transaction date and its balance
            start_date, start_balance = balance_data[0]
            # Newest transaction date and its balance
            end_date, end_balance = balance_data[-1]

            return {
                'start_balance': start_balance,
                'end_balance': end_balance,
                'start_date': start_date,
                'end_date': end_date
            }

        except Exception as e:
            print(f"Error extracting balances: {e}")
            return {
                'start_balance': None,
                'end_balance': None,
                'start_date': None,
                'end_date': None
            }
