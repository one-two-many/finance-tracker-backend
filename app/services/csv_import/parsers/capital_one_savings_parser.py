"""
Capital One Bank savings / CD account CSV parser.
"""
import csv
from io import StringIO
from typing import Any, Dict, List, Optional

from ..base_parser import CSVParser, ParsedTransaction
from ..utils import parse_date, calculate_header_confidence


def _parse_capone_amount(value: str) -> float:
    """Parse a Capital One savings amount/balance (plain number, optional $/commas)."""
    value = (value or "").strip()
    if not value:
        return 0.0
    cleaned = value.replace("$", "").replace(",", "").strip()
    return float(cleaned)


class CapitalOneSavingsParser(CSVParser):
    """
    Parser for Capital One Bank savings and CD CSV exports.

    Capital One Savings/CD CSV Format:
    - Account Number: last 4 of the account
    - Transaction Description: description of the transaction
    - Transaction Date: MM/DD/YY
    - Transaction Type: 'Credit' (money in) or 'Debit' (money out)
    - Transaction Amount: unsigned numeric amount (sign is implied by Transaction Type)
    - Balance: running account balance
    """

    TRANSFER_KEYWORDS = [
        "transfer", "payment", "zelle", "venmo", "ach", "wire",
        "online payment", "automatic payment", "withdrawal", "deposit",
    ]

    REFUND_KEYWORDS = [
        "refund", "return", "reversal", "chargeback",
    ]

    def get_name(self) -> str:
        return "capital_one_savings"

    def get_display_name(self) -> str:
        return "Capital One Savings / CD"

    def get_required_headers(self) -> List[str]:
        return [
            "Account Number",
            "Transaction Description",
            "Transaction Date",
            "Transaction Type",
            "Transaction Amount",
            "Balance",
        ]

    def get_parser_type(self) -> str:
        return "bank_account"

    def detect(self, csv_content: str) -> float:
        required_headers = set(self.get_required_headers())
        confidence = calculate_header_confidence(csv_content, required_headers)

        try:
            csv_reader = csv.DictReader(StringIO(csv_content))
            headers = set(csv_reader.fieldnames or [])

            # Boost: the 'Account Number' + single 'Transaction Amount' combo is distinctive
            if {"Account Number", "Transaction Amount"}.issubset(headers):
                confidence = min(1.0, confidence + 0.2)

            # Penalize formats that share some headers but aren't us:
            # Discover Savings uses separate Debit/Credit columns
            if {"Debit", "Credit"}.issubset(headers):
                confidence = max(0.0, confidence - 0.5)
            # Capital One credit-card export uses these unique headers
            if "Posted Date" in headers or "Card No." in headers:
                confidence = max(0.0, confidence - 0.5)

        except Exception:
            pass

        return confidence

    def parse(self, csv_content: str, account_type: Optional[str] = None) -> List[ParsedTransaction]:
        transactions: List[ParsedTransaction] = []
        csv_reader = csv.DictReader(StringIO(csv_content))

        if not csv_reader.fieldnames:
            raise ValueError("CSV file is empty or has no headers")

        headers = set(csv_reader.fieldnames)
        required = set(self.get_required_headers())
        if not required.issubset(headers):
            raise ValueError(
                f"Invalid Capital One Savings CSV format. "
                f"Expected headers: {required}. Found: {headers}"
            )

        for row in csv_reader:
            if not any(row.values()):
                continue

            date_str = (row.get("Transaction Date") or "").strip()
            description = (row.get("Transaction Description") or "").strip()
            txn_type_raw = (row.get("Transaction Type") or "").strip().lower()
            amount_str = (row.get("Transaction Amount") or "").strip()

            if not date_str or not description or not amount_str:
                continue

            try:
                transaction_date = parse_date(date_str, "%m/%d/%y")
                amount_abs = _parse_capone_amount(amount_str)
                if amount_abs <= 0:
                    continue

                is_credit = txn_type_raw == "credit"
                original_amount = amount_abs if is_credit else -amount_abs

                desc_lower = description.lower()
                if any(kw in desc_lower for kw in self.REFUND_KEYWORDS):
                    transaction_type = "refund"
                elif any(kw in desc_lower for kw in self.TRANSFER_KEYWORDS):
                    transaction_type = "transfer"
                elif is_credit:
                    # Credit that isn't a transfer/refund — treat as income (e.g. interest)
                    transaction_type = "income"
                else:
                    transaction_type = "expense"

                transactions.append(ParsedTransaction(
                    date=transaction_date,
                    amount=amount_abs,
                    description=description,
                    transaction_type=transaction_type,
                    category=None,
                    notes=None,
                    raw_data=dict(row),
                    original_amount=original_amount,
                ))

            except Exception:
                continue

        return transactions

    def extract_balances(self, csv_content: str) -> Optional[Dict[str, Any]]:
        """
        Extract start/end balance snapshots from the Balance column so the
        net-worth feature can seed manual snapshots on first import.
        """
        try:
            rows = list(csv.DictReader(StringIO(csv_content)))
        except Exception:
            return None

        dated: List[tuple] = []
        for r in rows:
            d = (r.get("Transaction Date") or "").strip()
            b = (r.get("Balance") or "").strip()
            if not d or not b:
                continue
            try:
                dt = parse_date(d, "%m/%d/%y")
                bal = _parse_capone_amount(b)
            except Exception:
                continue
            dated.append((dt, bal))

        if not dated:
            return None

        dated.sort(key=lambda x: x[0])
        return {
            "start_balance": dated[0][1],
            "end_balance": dated[-1][1],
            "start_date": dated[0][0],
            "end_date": dated[-1][0],
        }
