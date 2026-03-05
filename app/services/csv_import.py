import csv
from datetime import datetime
from decimal import Decimal
from typing import List
from io import StringIO
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.transaction import Transaction, TransactionType
from app.models.category import Category
from app.schemas.csv_import import TransactionImportResult


def parse_amex_date(date_str: str) -> datetime:
    """
    Parse AMEX date format (MM/DD/YYYY) to datetime object.

    Args:
        date_str: Date string in MM/DD/YYYY format

    Returns:
        datetime: Parsed datetime object

    Raises:
        ValueError: If date format is invalid
    """
    return datetime.strptime(date_str.strip(), "%m/%d/%Y")


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

    AMEX CSV Format:
    - Date: MM/DD/YYYY
    - Description: Transaction description
    - Amount: Positive = expense, Negative = income/payment
    - Appears On Your Statement As: Additional info (saved to notes)
    - Category: AMEX category name

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

    # Parse CSV
    csv_reader = csv.DictReader(StringIO(file_content))

    # Expected AMEX CSV headers
    expected_headers = {"Date", "Description", "Amount"}

    # Validate headers exist
    if not expected_headers.issubset(set(csv_reader.fieldnames or [])):
        raise ValueError(
            f"Invalid CSV format. Expected headers: {expected_headers}. "
            f"Found: {csv_reader.fieldnames}"
        )

    row_number = 1  # Start from 1 (after header)

    for row in csv_reader:
        row_number += 1

        try:
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
                results.append(TransactionImportResult(
                    row_number=row_number,
                    status="error",
                    message="Missing required fields (Date, Description, or Amount)"
                ))
                error_count += 1
                continue

            # Parse date
            try:
                transaction_date = parse_amex_date(date_str)
            except ValueError as e:
                results.append(TransactionImportResult(
                    row_number=row_number,
                    status="error",
                    message=f"Invalid date format: {date_str}"
                ))
                error_count += 1
                continue

            # Parse amount
            try:
                # Remove currency symbols and commas
                amount_clean = amount_str.replace("$", "").replace(",", "").strip()
                amount_value = Decimal(amount_clean)
            except Exception as e:
                results.append(TransactionImportResult(
                    row_number=row_number,
                    status="error",
                    message=f"Invalid amount: {amount_str}"
                ))
                error_count += 1
                continue

            # Determine transaction type based on amount sign
            # Positive = EXPENSE (purchases, charges)
            # Negative = INCOME (payments, refunds, credits)
            if amount_value >= 0:
                transaction_type = TransactionType.EXPENSE
                amount_abs = amount_value
            else:
                transaction_type = TransactionType.INCOME
                amount_abs = abs(amount_value)

            # Check for duplicates
            if skip_duplicates and is_duplicate(
                db, user_id, account_id, transaction_date, amount_abs, description
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
            if category_name:
                # Check if this category was just created
                category_existed = db.query(Category).filter(
                    Category.user_id == user_id,
                    func.lower(Category.name) == category_name.lower()
                ).first() is not None

                category = find_or_create_category(db, user_id, category_name)

                if not category_existed:
                    categories_created.add(category_name)

            # Create notes from statement_as
            notes = statement_as if statement_as else None

            # Create transaction
            transaction = Transaction(
                user_id=user_id,
                account_id=account_id,
                category_id=category.id if category else None,
                transaction_type=transaction_type,
                amount=amount_abs,
                description=description,
                notes=notes,
                transaction_date=transaction_date
            )
            db.add(transaction)

            results.append(TransactionImportResult(
                row_number=row_number,
                status="created",
                message=None
            ))
            created_count += 1

        except Exception as e:
            # Catch any unexpected errors
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
        "total_rows": row_number - 1,  # Exclude header
        "created": created_count,
        "skipped": skipped_count,
        "errors": error_count,
        "results": results,
        "categories_created": sorted(list(categories_created))
    }
