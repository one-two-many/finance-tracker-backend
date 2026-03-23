"""
CSV Import Service - Orchestrates parsing, categorization, and import.
"""
from typing import Dict, List, Optional, Union
from sqlalchemy.orm import Session
from datetime import datetime

from opentelemetry import trace

from app.models.transaction import Transaction, TransactionType
from app.models.category import Category
from app.models.account import Account
from app.models.account_balance_snapshot import AccountBalanceSnapshot
from app.core.logging import get_logger
from app.core.telemetry import get_csv_import_counter, get_csv_import_rows_histogram

from .parser_registry import registry
from .base_parser import ParsedTransaction
from .legacy import is_duplicate, find_or_create_category
from .category_suggester import CategorySuggester
from .transfer_detector import TransferDetector

logger = get_logger(__name__)
tracer = trace.get_tracer(__name__)


class CSVImportService:
    """
    Orchestrates CSV import operations including:
    - Parser detection
    - Transaction parsing
    - Category suggestion
    - Duplicate detection
    - Database persistence
    """

    def __init__(self, db: Session, user_id: int):
        self.db = db
        self.user_id = user_id
        self.category_suggester = CategorySuggester(db, user_id)
        self.transfer_detector = TransferDetector(db, user_id)

    def preview_import(
        self,
        file_content: Union[str, bytes],
        account_id: int,
        parser_name: Optional[str] = None
    ) -> Dict:
        """
        Preview import without saving to database.

        Args:
            file_content: File content (str for CSV, bytes for PDF)
            account_id: Account ID for transactions
            parser_name: Optional parser name (auto-detect if not provided)

        Returns:
            Dict with preview data including parsed transactions
        """
        # Fetch account to get account type
        account = self.db.query(Account).filter(Account.id == account_id).first()
        account_type = account.account_type.value if account and account.account_type else None

        logger.info("csv_preview_start", account_id=account_id, parser_name=parser_name)

        # Auto-detect parser if not specified
        if not parser_name:
            detected = registry.detect_parser(file_content, min_confidence=0.5)
            if not detected:
                return {
                    "error": "Could not detect CSV format. Please select parser manually.",
                    "parser_used": None,
                    "confidence": 0.0,
                    "alternatives": []
                }

            parser_name = detected[0][0]
            confidence = detected[0][1]
            alternatives = detected[1:] if len(detected) > 1 else []
        else:
            confidence = 1.0
            alternatives = []

        # Get parser
        parser = registry.get_parser(parser_name)
        if not parser:
            return {
                "error": f"Parser '{parser_name}' not found",
                "parser_used": parser_name,
                "confidence": 0.0
            }

        # Parse transactions with account type for intelligent classification
        try:
            parsed_transactions = parser.parse(file_content, account_type=account_type)
        except ValueError as e:
            return {
                "error": str(e),
                "parser_used": parser_name,
                "confidence": confidence
            }

        # Check for duplicates and prepare preview data
        preview_data = []
        duplicate_count = 0
        transfer_candidates = []

        for parsed_tx in parsed_transactions:
            is_dup = is_duplicate(
                self.db,
                self.user_id,
                account_id,
                parsed_tx.date,
                parsed_tx.amount,
                parsed_tx.description
            )

            if is_dup:
                duplicate_count += 1

            # Suggest category if not provided by parser
            suggested_category = parsed_tx.category
            if not suggested_category:
                suggestion = self.category_suggester.suggest_category(parsed_tx.description)
                if suggestion:
                    _, category_name, _ = suggestion
                    suggested_category = category_name

            # Check if it's a transfer candidate
            transfer_candidate = self.transfer_detector.detect_transfer(parsed_tx, account_id)
            is_transfer = transfer_candidate is not None
            transfer_target_account_name = None
            transfer_target_account_id = None

            if is_transfer:
                transfer_target_account_name = transfer_candidate.target_account_name
                transfer_target_account_id = transfer_candidate.target_account_id
                transfer_candidates.append({
                    "description": parsed_tx.description,
                    "amount": float(parsed_tx.amount),
                    "date": parsed_tx.date.isoformat(),
                    "target_account": transfer_target_account_name,
                    "confidence": transfer_candidate.confidence
                })

            preview_data.append({
                "date": parsed_tx.date.isoformat(),
                "description": parsed_tx.description,
                "amount": float(parsed_tx.amount),
                "original_amount": float(parsed_tx.original_amount) if parsed_tx.original_amount is not None else float(parsed_tx.amount),
                "type": parsed_tx.transaction_type,
                "suggested_category": suggested_category,
                "is_duplicate": is_dup,
                "is_transfer_candidate": is_transfer,
                "transfer_target_account": transfer_target_account_name,
                "transfer_target_account_id": transfer_target_account_id,
                "notes": parsed_tx.notes
            })

        return {
            "parser_used": parser_name,
            "parser_display_name": parser.get_display_name(),
            "confidence": confidence,
            "alternatives": [
                {"name": name, "confidence": conf}
                for name, conf in alternatives
            ],
            "total_transactions": len(parsed_transactions),
            "duplicate_count": duplicate_count,
            "transfer_candidate_count": len(transfer_candidates),
            "transactions": preview_data,
            "transfer_candidates": transfer_candidates
        }

    def import_transactions(
        self,
        file_content: Union[str, bytes],
        account_id: int,
        parser_name: str,
        category_mappings: Optional[Dict[str, int]] = None,
        type_overrides: Optional[Dict[str, str]] = None,
        skip_duplicates: bool = True,
        filename: Optional[str] = None
    ) -> Dict:
        """
        Import transactions with user-reviewed categories and types.

        Args:
            file_content: File content (str for CSV, bytes for PDF)
            account_id: Account ID for transactions
            parser_name: Parser to use
            category_mappings: Dict mapping description -> category_id
            type_overrides: Dict mapping description -> transaction_type (income/expense/transfer/refund)
            skip_duplicates: Whether to skip duplicate transactions
            filename: Original filename

        Returns:
            Dict with import summary
        """
        with tracer.start_as_current_span("csv_import", attributes={
            "csv.parser": parser_name,
            "csv.account_id": account_id,
            "csv.skip_duplicates": skip_duplicates,
        }) as span:
            return self._do_import(
                span, file_content, account_id, parser_name,
                category_mappings, type_overrides, skip_duplicates, filename,
            )

    def _do_import(self, span, file_content, account_id, parser_name,
                   category_mappings, type_overrides, skip_duplicates, filename):
        logger.info("csv_import_start", parser=parser_name, account_id=account_id)

        # Fetch account to get account type
        account = self.db.query(Account).filter(Account.id == account_id).first()
        if not account:
            raise ValueError(f"Account with id {account_id} not found")
        account_type = account.account_type.value if account.account_type else None

        # Get parser
        parser = registry.get_parser(parser_name)
        if not parser:
            raise ValueError(f"Parser '{parser_name}' not found")

        # Parse transactions with account type
        parsed_transactions = parser.parse(file_content, account_type=account_type)

        span.set_attribute("csv.total_rows", len(parsed_transactions))

        # Import transactions
        created_count = 0
        skipped_count = 0
        error_count = 0
        categories_created = set()

        for parsed_tx in parsed_transactions:
            try:
                # Check for duplicates
                if skip_duplicates and is_duplicate(
                    self.db,
                    self.user_id,
                    account_id,
                    parsed_tx.date,
                    parsed_tx.amount,
                    parsed_tx.description
                ):
                    skipped_count += 1
                    continue

                # Determine category
                category_id = None
                if category_mappings and parsed_tx.description in category_mappings:
                    category_id = category_mappings[parsed_tx.description]
                elif parsed_tx.category:
                    category = find_or_create_category(
                        self.db,
                        self.user_id,
                        parsed_tx.category
                    )
                    category_id = category.id
                    categories_created.add(parsed_tx.category)

                # Check for type override from user
                transaction_type_str = parsed_tx.transaction_type
                if type_overrides and parsed_tx.description in type_overrides:
                    transaction_type_str = type_overrides[parsed_tx.description]

                # Map transaction type and handle special cases
                transfer_to_account_id = None

                if transaction_type_str == "income":
                    tx_type = TransactionType.INCOME
                elif transaction_type_str == "expense":
                    tx_type = TransactionType.EXPENSE
                elif transaction_type_str == "transfer":
                    tx_type = TransactionType.TRANSFER
                    # Try to detect the target account for the transfer
                    transfer_candidate = self.transfer_detector.detect_transfer(parsed_tx, account_id)
                    if transfer_candidate and transfer_candidate.target_account_id:
                        transfer_to_account_id = transfer_candidate.target_account_id
                elif transaction_type_str == "card_payment":
                    tx_type = TransactionType.CARD_PAYMENT
                elif transaction_type_str == "refund":
                    tx_type = TransactionType.REFUND
                else:
                    tx_type = TransactionType.TRANSFER

                # Create transaction
                transaction = Transaction(
                    user_id=self.user_id,
                    account_id=account_id,
                    category_id=category_id,
                    transaction_type=tx_type,
                    amount=parsed_tx.amount,
                    description=parsed_tx.description,
                    notes=parsed_tx.notes,
                    transaction_date=parsed_tx.date,
                    transfer_to_account_id=transfer_to_account_id
                )
                self.db.add(transaction)
                self.db.flush()  # Flush to get transaction ID for linking
                created_count += 1

                # If it's a transfer with a target account, create matching transaction
                if tx_type == TransactionType.TRANSFER and transfer_to_account_id:
                    # Check if matching transaction already exists to avoid duplicates
                    # Look for transaction on target account with same date, amount, and description
                    existing_match = self.db.query(Transaction).filter(
                        Transaction.user_id == self.user_id,
                        Transaction.account_id == transfer_to_account_id,
                        Transaction.transaction_date == parsed_tx.date,
                        Transaction.amount == parsed_tx.amount,
                        Transaction.description == parsed_tx.description,
                        Transaction.transaction_type == TransactionType.TRANSFER
                    ).first()

                    if not existing_match:
                        # Create matching transaction on target account
                        matching_transaction = Transaction(
                            user_id=self.user_id,
                            account_id=transfer_to_account_id,
                            category_id=category_id,  # Use same category
                            transaction_type=TransactionType.TRANSFER,
                            amount=parsed_tx.amount,
                            description=parsed_tx.description,
                            notes=f"Auto-created transfer from {account.name}" if parsed_tx.notes is None else f"{parsed_tx.notes} (from {account.name})",
                            transaction_date=parsed_tx.date,
                            transfer_to_account_id=account_id  # Link back to source account
                        )
                        self.db.add(matching_transaction)
                        self.db.flush()

                        # Update original transaction to link to the matching one
                        # Note: We already set transfer_to_account_id, but this creates the full bidirectional link
                        created_count += 1
                    else:
                        # Link to existing matching transaction
                        transaction.transfer_to_account_id = transfer_to_account_id
                        if not existing_match.transfer_to_account_id:
                            existing_match.transfer_to_account_id = account_id

            except Exception as e:
                error_count += 1
                continue

        # Commit transactions
        try:
            self.db.commit()
        except Exception as e:
            self.db.rollback()
            logger.error("csv_import_commit_failed", error=str(e), parser=parser_name)
            raise Exception(f"Failed to save transactions: {str(e)}")

        # Extract and save balance snapshots if parser supports it
        balance_info = None
        if hasattr(parser, 'extract_balances'):
            try:
                balance_data = parser.extract_balances(file_content)
                if balance_data and balance_data.get('start_balance') is not None:
                    self._save_balance_snapshots(
                        account_id=account_id,
                        balance_data=balance_data
                    )
                    balance_info = {
                        'start_balance': float(balance_data['start_balance']),
                        'end_balance': float(balance_data['end_balance']),
                        'start_date': balance_data['start_date'].isoformat() if balance_data.get('start_date') else None,
                        'end_date': balance_data['end_date'].isoformat() if balance_data.get('end_date') else None
                    }
            except Exception as e:
                logger.warning("balance_extraction_failed", error=str(e))
                # Don't fail the import if balance extraction fails

        result = {
            "total_rows": len(parsed_transactions),
            "created": created_count,
            "skipped": skipped_count,
            "errors": error_count,
            "categories_created": sorted(list(categories_created))
        }

        if balance_info:
            result['balance_info'] = balance_info

        # Record metrics
        try:
            get_csv_import_counter().add(1, {"parser": parser_name, "status": "success"})
            get_csv_import_rows_histogram().record(created_count, {"parser": parser_name})
        except Exception:
            pass

        span.set_attributes({
            "csv.created": created_count,
            "csv.skipped": skipped_count,
            "csv.errors": error_count,
        })

        logger.info(
            "csv_import_complete",
            parser=parser_name,
            total=len(parsed_transactions),
            created=created_count,
            skipped=skipped_count,
            errors=error_count,
        )

        return result

    def _save_balance_snapshots(self, account_id: int, balance_data: Dict):
        """
        Save balance snapshots to database.

        Args:
            account_id: Account ID
            balance_data: Dict with start_balance, end_balance, start_date, end_date
        """
        start_balance = balance_data.get('start_balance')
        end_balance = balance_data.get('end_balance')
        start_date = balance_data.get('start_date')
        end_date = balance_data.get('end_date')

        if not all([start_balance is not None, end_balance is not None, start_date, end_date]):
            return

        # Extract period information
        period_year = start_date.year
        period_month = start_date.month

        # Check if snapshots already exist (to avoid duplicates)
        existing_start = self.db.query(AccountBalanceSnapshot).filter(
            AccountBalanceSnapshot.user_id == self.user_id,
            AccountBalanceSnapshot.account_id == account_id,
            AccountBalanceSnapshot.snapshot_date == start_date.date() if hasattr(start_date, 'date') else start_date,
            AccountBalanceSnapshot.snapshot_type == 'start'
        ).first()

        existing_end = self.db.query(AccountBalanceSnapshot).filter(
            AccountBalanceSnapshot.user_id == self.user_id,
            AccountBalanceSnapshot.account_id == account_id,
            AccountBalanceSnapshot.snapshot_date == end_date.date() if hasattr(end_date, 'date') else end_date,
            AccountBalanceSnapshot.snapshot_type == 'end'
        ).first()

        # Create or update start balance snapshot
        if existing_start:
            existing_start.balance = start_balance
            existing_start.period_year = period_year
            existing_start.period_month = period_month
        else:
            start_snapshot = AccountBalanceSnapshot(
                user_id=self.user_id,
                account_id=account_id,
                balance=start_balance,
                snapshot_date=start_date.date() if hasattr(start_date, 'date') else start_date,
                snapshot_type='start',
                period_year=period_year,
                period_month=period_month
            )
            self.db.add(start_snapshot)

        # Create or update end balance snapshot
        if existing_end:
            existing_end.balance = end_balance
            existing_end.period_year = period_year
            existing_end.period_month = period_month
        else:
            end_snapshot = AccountBalanceSnapshot(
                user_id=self.user_id,
                account_id=account_id,
                balance=end_balance,
                snapshot_date=end_date.date() if hasattr(end_date, 'date') else end_date,
                snapshot_type='end',
                period_year=period_year,
                period_month=period_month
            )
            self.db.add(end_snapshot)

        try:
            self.db.commit()
        except Exception as e:
            self.db.rollback()
            logger.warning("balance_snapshot_save_failed", error=str(e))
            # Don't raise - balance tracking is supplementary
