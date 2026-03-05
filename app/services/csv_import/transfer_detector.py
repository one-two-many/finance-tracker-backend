"""
Transfer detection service for identifying transfers between accounts.
"""
from typing import List, Optional, Tuple
from decimal import Decimal
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from app.models.account import Account
from app.models.transaction import Transaction, TransactionType
from ..csv_import.base_parser import ParsedTransaction


class TransferCandidate:
    """Represents a potential transfer transaction."""

    def __init__(
        self,
        transaction: ParsedTransaction,
        confidence: float,
        target_account_id: Optional[int] = None,
        target_account_name: Optional[str] = None,
        matching_transaction_id: Optional[int] = None
    ):
        self.transaction = transaction
        self.confidence = confidence
        self.target_account_id = target_account_id
        self.target_account_name = target_account_name
        self.matching_transaction_id = matching_transaction_id


class TransferDetector:
    """
    Detects transactions that are likely transfers between user's accounts.

    Detection strategies:
    1. Keyword matching in description
    2. Matching against account names and last 4 digits
    3. Finding matching opposite transactions (same date, same amount)
    """

    # Keywords that indicate transfers
    TRANSFER_KEYWORDS = [
        "transfer",
        "payment to",
        "payment from",
        "payment received",
        "ach credit",
        "ach debit",
        "wire",
        "zelle",
        "venmo",
        "online transfer",
        "mobile transfer",
        "account transfer",
        "internal transfer",
        "credit card payment",
        "automatic payment",
        "autopay",
        "online banking payment",
        "direct debit",
        "bill payment"
    ]

    # Keywords that indicate refunds (should be expense offsets, not income)
    REFUND_KEYWORDS = [
        "refund",
        "return",
        "reversal",
        "chargeback",
        "credit adjustment",
        "dispute resolution"
    ]

    # Keywords that indicate cashback/rewards (could be income or expense offset)
    CASHBACK_KEYWORDS = [
        "cashback",
        "cash back",
        "rewards",
        "reward credit",
        "points credit",
        "statement credit",
        "promotional credit",
        "bonus"
    ]

    def __init__(self, db: Session, user_id: int):
        self.db = db
        self.user_id = user_id
        self._user_accounts = None

    @staticmethod
    def is_refund(description: str) -> bool:
        """
        Check if transaction description indicates a refund.

        Args:
            description: Transaction description

        Returns:
            bool: True if description contains refund keywords
        """
        desc_lower = description.lower()
        return any(keyword in desc_lower for keyword in TransferDetector.REFUND_KEYWORDS)

    @staticmethod
    def is_cashback(description: str) -> bool:
        """
        Check if transaction description indicates cashback/rewards.

        Args:
            description: Transaction description

        Returns:
            bool: True if description contains cashback keywords
        """
        desc_lower = description.lower()
        return any(keyword in desc_lower for keyword in TransferDetector.CASHBACK_KEYWORDS)

    def _load_user_accounts(self):
        """Load and cache user's accounts."""
        if self._user_accounts is None:
            self._user_accounts = (
                self.db.query(Account)
                .filter(Account.user_id == self.user_id)
                .all()
            )

    def detect_transfer(
        self,
        parsed_tx: ParsedTransaction,
        source_account_id: int
    ) -> Optional[TransferCandidate]:
        """
        Analyze a transaction to determine if it's likely a transfer.

        Args:
            parsed_tx: Parsed transaction to analyze
            source_account_id: Account ID where transaction originated

        Returns:
            Optional[TransferCandidate]: Transfer candidate if detected, None otherwise
        """
        desc_lower = parsed_tx.description.lower()

        # Check for transfer keywords
        has_transfer_keyword = any(
            keyword in desc_lower for keyword in self.TRANSFER_KEYWORDS
        )

        if not has_transfer_keyword and not parsed_tx.transfer_account_identifier:
            return None

        # Load user accounts
        self._load_user_accounts()

        # Try to match account names or last 4 digits
        target_account = self._match_account(desc_lower, source_account_id)

        # Try to find matching opposite transaction
        matching_tx = self._find_matching_transaction(
            parsed_tx, source_account_id, target_account.id if target_account else None
        )

        # Calculate confidence
        confidence = 0.0

        if has_transfer_keyword:
            confidence += 0.5

        if target_account:
            confidence += 0.3

        if matching_tx:
            confidence += 0.2

        if confidence < 0.3:
            return None

        return TransferCandidate(
            transaction=parsed_tx,
            confidence=min(1.0, confidence),
            target_account_id=target_account.id if target_account else None,
            target_account_name=target_account.name if target_account else None,
            matching_transaction_id=matching_tx.id if matching_tx else None
        )

    def _match_account(
        self,
        description: str,
        exclude_account_id: int
    ) -> Optional[Account]:
        """
        Try to match description against user's account names or last 4 digits.

        Args:
            description: Lowercase transaction description
            exclude_account_id: Don't match this account (the source)

        Returns:
            Optional[Account]: Matching account if found
        """
        for account in self._user_accounts:
            if account.id == exclude_account_id:
                continue

            # Check account name
            if account.name.lower() in description:
                return account

            # Check last 4 digits
            if account.account_number_last4:
                if account.account_number_last4 in description:
                    return account

        return None

    def _find_matching_transaction(
        self,
        parsed_tx: ParsedTransaction,
        source_account_id: int,
        target_account_id: Optional[int] = None
    ) -> Optional[Transaction]:
        """
        Find existing transaction that matches (opposite sign, same amount, similar date).

        Args:
            parsed_tx: Transaction to match
            source_account_id: Source account ID
            target_account_id: Optional target account ID to narrow search

        Returns:
            Optional[Transaction]: Matching transaction if found
        """
        # Look for transactions within 3 days
        date_start = parsed_tx.date - timedelta(days=3)
        date_end = parsed_tx.date + timedelta(days=3)

        # Determine opposite transaction type
        if parsed_tx.transaction_type == "income":
            opposite_type = TransactionType.EXPENSE
        else:
            opposite_type = TransactionType.INCOME

        # Build query
        query = self.db.query(Transaction).filter(
            Transaction.user_id == self.user_id,
            Transaction.account_id != source_account_id,
            Transaction.transaction_type == opposite_type,
            Transaction.amount == parsed_tx.amount,
            Transaction.transaction_date >= date_start,
            Transaction.transaction_date <= date_end
        )

        if target_account_id:
            query = query.filter(Transaction.account_id == target_account_id)

        return query.first()

    def detect_batch(
        self,
        parsed_transactions: List[ParsedTransaction],
        source_account_id: int
    ) -> List[Optional[TransferCandidate]]:
        """
        Detect transfers in a batch of transactions.

        Args:
            parsed_transactions: List of parsed transactions
            source_account_id: Source account ID

        Returns:
            List of transfer candidates (same length as input, None where no transfer detected)
        """
        return [
            self.detect_transfer(tx, source_account_id)
            for tx in parsed_transactions
        ]
