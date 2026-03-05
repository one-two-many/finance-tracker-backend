"""
Chase Bank PDF statement parser.
"""
import pdfplumber
import re
from io import BytesIO
from typing import List, Optional
from datetime import datetime

from ..base_pdf_parser import PDFParser
from ..base_parser import ParsedTransaction
from ..utils import parse_amount


class ChaseBankPDFParser(PDFParser):
    """
    Parser for Chase Bank PDF statements.

    Chase Bank PDF Format:
    - Header: "Chase College Checking" or similar
    - Transaction section starts with "TRANSACTION DETAIL"
    - Format: DATE DESCRIPTION AMOUNT BALANCE
    - Date format: MM/DD (year inferred from statement date range)
    - Amount: Negative = expense/withdrawal, Positive = deposit/income
    """

    def get_name(self) -> str:
        return "chase_bank_pdf"

    def get_display_name(self) -> str:
        return "Chase Bank PDF Statement"

    def detect(self, pdf_bytes: bytes) -> float:
        """
        Detect Chase Bank PDF format by checking for specific text.
        """
        try:
            with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
                if not pdf.pages:
                    return 0.0

                # Get first page text
                text = pdf.pages[0].extract_text()
                if not text:
                    return 0.0

                confidence = 0.0

                # Check for Chase identifiers
                if "JPMorgan Chase Bank" in text or "Chase.com" in text:
                    confidence += 0.4

                if "Chase College Checking" in text or "Chase Total Checking" in text:
                    confidence += 0.3

                if "TRANSACTION DETAIL" in text:
                    confidence += 0.3

                return min(1.0, confidence)

        except Exception:
            return 0.0

    def parse(self, pdf_bytes: bytes, account_type: Optional[str] = None) -> List[ParsedTransaction]:
        """
        Parse Chase Bank PDF into standardized transactions.

        Args:
            pdf_bytes: Raw PDF file bytes
            account_type: Account type for intelligent classification
        """
        transactions = []

        try:
            with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
                # Extract statement date range for year inference
                statement_year = datetime.now().year  # Default to current year

                for page in pdf.pages:
                    text = page.extract_text()
                    if not text:
                        continue

                    # Try to extract year from statement date range (e.g., "December 19, 2025 through January 22, 2026")
                    date_range_match = re.search(r'(\w+\s+\d+,\s+(\d{4}))\s+through', text)
                    if date_range_match:
                        statement_year = int(date_range_match.group(2))

                    # Find transaction detail section
                    lines = text.split('\n')
                    in_transactions = False

                    for i, line in enumerate(lines):
                        # Start of transaction section
                        if 'TRANSACTION DETAIL' in line:
                            in_transactions = True
                            continue

                        # End of transaction section
                        if '*end*transaction detail' in line.lower() or 'ending balance' in line.lower():
                            # Check if "Ending Balance" is a standalone line or part of transaction
                            if line.strip().startswith('Ending Balance'):
                                in_transactions = False
                                continue

                        if not in_transactions:
                            continue

                        # Skip header row
                        if 'DATE' in line and 'DESCRIPTION' in line:
                            continue

                        # Skip "Beginning Balance" line
                        if 'Beginning Balance' in line:
                            continue

                        # Parse transaction line
                        # Format: MM/DD Description Amount Balance
                        # Example: "12/22 Zelle Payment To Siddesh Rao 27052758053 -36.00 6,044.59"

                        # Match date at start of line
                        date_match = re.match(r'^(\d{1,2}/\d{1,2})\s+(.+)$', line)
                        if not date_match:
                            continue

                        date_str = date_match.group(1)
                        rest = date_match.group(2).strip()

                        # Extract amount and balance from the end
                        # They are typically the last two numeric values
                        # Pattern: ... -123.45 1,234.56 or ... 123.45 1,234.56
                        amount_balance_match = re.search(r'(-?[\d,]+\.\d{2})\s+([\d,]+\.\d{2})$', rest)

                        if not amount_balance_match:
                            # Sometimes balance might be missing, just look for amount
                            amount_balance_match = re.search(r'(-?[\d,]+\.\d{2})$', rest)
                            if not amount_balance_match:
                                continue

                        amount_str = amount_balance_match.group(1)

                        # Description is everything between date and amount
                        description = rest[:amount_balance_match.start()].strip()

                        if not description:
                            continue

                        try:
                            # Parse date (MM/DD format, add year)
                            month, day = map(int, date_str.split('/'))

                            # Handle year rollover (e.g., Dec 2025 -> Jan 2026)
                            # If month is 01 and we haven't seen Jan yet, it's next year
                            if month == 1:
                                # Check if statement spans year boundary
                                if 'through' in text.lower():
                                    # Use the "through" year if crossing year boundary
                                    through_match = re.search(r'through\s+\w+\s+\d+,\s+(\d{4})', text)
                                    if through_match:
                                        statement_year = int(through_match.group(1))

                            transaction_date = datetime(statement_year, month, day)

                            # Parse amount
                            amount_value = parse_amount(amount_str)

                            # Determine transaction type based on amount sign
                            if amount_value < 0:
                                transaction_type = "expense"
                                amount_abs = abs(amount_value)
                            else:
                                transaction_type = "income"
                                amount_abs = amount_value

                            # Create transaction
                            transaction = ParsedTransaction(
                                date=transaction_date,
                                amount=amount_abs,
                                description=description,
                                transaction_type=transaction_type,
                                category=None,  # No category in Chase PDFs
                                notes=None,
                                raw_data={"original_line": line},
                                original_amount=amount_value  # Preserve original signed amount from PDF
                            )

                            transactions.append(transaction)

                        except (ValueError, Exception) as e:
                            # Skip rows with parsing errors
                            continue

        except Exception as e:
            raise ValueError(f"Error parsing Chase Bank PDF: {str(e)}")

        if not transactions:
            raise ValueError("No transactions found in PDF. Please check if this is a valid Chase Bank statement.")

        return transactions
