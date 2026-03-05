"""
Legacy CSV import functions for backwards compatibility.

These functions maintain the original API while using the new parser system internally.
"""
from datetime import datetime
from decimal import Decimal
from typing import List
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.transaction import Transaction, TransactionType
from app.models.category import Category
from app.schemas.csv_import import TransactionImportResult

from .parser_registry import registry


def is_duplicate(
    db: Session,
    user_id: int,
    account_id: int,
    date: datetime,
    amount: Decimal,
    description: str
) -> bool:
    """
    Check if a transaction with the same details already exists.

    Args:
        db: Database session
        user_id: User ID
        account_id: Account ID
        date: Transaction date
        amount: Transaction amount
        description: Transaction description

    Returns:
        bool: True if duplicate exists, False otherwise
    """
    existing = db.query(Transaction).filter(
        Transaction.user_id == user_id,
        Transaction.account_id == account_id,
        Transaction.transaction_date == date,
        Transaction.amount == amount,
        Transaction.description == description
    ).first()

    return existing is not None


def find_or_create_category(
    db: Session,
    user_id: int,
    category_name: str
) -> Category:
    """
    Find an existing category by name (case-insensitive) or create a new one.

    Args:
        db: Database session
        user_id: User ID
        category_name: Category name from CSV

    Returns:
        Category: Existing or newly created category
    """
    # Search for existing category (case-insensitive)
    existing_category = db.query(Category).filter(
        Category.user_id == user_id,
        func.lower(Category.name) == category_name.strip().lower()
    ).first()

    if existing_category:
        return existing_category

    # Create new category with default values
    new_category = Category(
        user_id=user_id,
        name=category_name.strip(),
        color="#6B7280",  # Default gray color
        icon="tag"  # Default icon
    )
    db.add(new_category)
    db.flush()  # Get the ID without committing

    return new_category


def parse_amex_csv(
    file_content: str,
    user_id: int,
    account_id: int,
    db: Session,
    skip_duplicates: bool = True
) -> dict:
    """
    Parse AMEX CSV file and create transactions.

    This is a legacy function maintained for backwards compatibility.
    It uses the new AmexParser internally.

    Args:
        file_content: CSV file content as string
        user_id: User ID
        account_id: Account ID to associate transactions with
        db: Database session
        skip_duplicates: Whether to skip duplicate transactions

    Returns:
        dict: Import summary with results and statistics
    """
    results: List[TransactionImportResult] = []
    created_count = 0
    skipped_count = 0
    error_count = 0
    categories_created = set()

    # Get AMEX parser from registry
    amex_parser = registry.get_parser("amex")
    if not amex_parser:
        raise ValueError("AMEX parser not available")

    # Parse CSV using new parser
    try:
        parsed_transactions = amex_parser.parse(file_content)
    except ValueError as e:
        raise ValueError(str(e))

    row_number = 1
    for parsed_tx in parsed_transactions:
        row_number += 1

        try:
            # Check for duplicates
            if skip_duplicates and is_duplicate(
                db, user_id, account_id, parsed_tx.date, parsed_tx.amount, parsed_tx.description
            ):
                results.append(TransactionImportResult(
                    row_number=row_number,
                    status="skipped",
                    message="Duplicate transaction"
                ))
                skipped_count += 1
                continue

            # Find or create category
            category = None
            if parsed_tx.category:
                # Check if this category was just created
                category_existed = db.query(Category).filter(
                    Category.user_id == user_id,
                    func.lower(Category.name) == parsed_tx.category.lower()
                ).first() is not None

                category = find_or_create_category(db, user_id, parsed_tx.category)

                if not category_existed:
                    categories_created.add(parsed_tx.category)

            # Map transaction type to enum
            if parsed_tx.transaction_type == "income":
                tx_type = TransactionType.INCOME
            elif parsed_tx.transaction_type == "expense":
                tx_type = TransactionType.EXPENSE
            else:
                tx_type = TransactionType.TRANSFER

            # Create transaction
            transaction = Transaction(
                user_id=user_id,
                account_id=account_id,
                category_id=category.id if category else None,
                transaction_type=tx_type,
                amount=parsed_tx.amount,
                description=parsed_tx.description,
                notes=parsed_tx.notes,
                transaction_date=parsed_tx.date
            )
            db.add(transaction)

            results.append(TransactionImportResult(
                row_number=row_number,
                status="created",
                message=None
            ))
            created_count += 1

        except Exception as e:
            results.append(TransactionImportResult(
                row_number=row_number,
                status="error",
                message=f"Unexpected error: {str(e)}"
            ))
            error_count += 1
            continue

    # Commit all transactions
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise Exception(f"Failed to save transactions: {str(e)}")

    return {
        "total_rows": len(parsed_transactions),
        "created": created_count,
        "skipped": skipped_count,
        "errors": error_count,
        "results": results,
        "categories_created": sorted(list(categories_created))
    }
