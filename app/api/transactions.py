from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, Body, Query
from sqlalchemy.orm import Session
from datetime import datetime
from typing import Optional, List
import base64
from pydantic import BaseModel

from app.core.database import get_db
from app.api.dependencies import get_current_user
from app.models.user import User
from app.models.account import Account
from app.models.import_session import ImportSession
from app.models.transaction import Transaction, TransactionType
from app.models.category import Category
from app.models.account_balance_snapshot import AccountBalanceSnapshot
from app.schemas.csv_import import CSVImportResponse
from app.schemas.parser import ImportPreviewResponse, ImportConfirmRequest, ImportConfirmResponse
from app.services.csv_import import parse_amex_csv
from app.services.csv_import.import_service import CSVImportService

router = APIRouter()

# Maximum file size: 10MB
MAX_FILE_SIZE = 10 * 1024 * 1024


@router.get("")
async def list_transactions(
    start_date: Optional[str] = Query(None, description="Start date filter (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date filter (YYYY-MM-DD)"),
    account_id: Optional[str] = Query(None, description="Filter by account ID(s), comma-separated for multiple"),
    category_id: Optional[str] = Query(None, description="Filter by category ID(s), comma-separated for multiple"),
    transaction_type: Optional[str] = Query(None, description="Filter by type (income/expense/transfer)"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List all transactions for the current user with optional filters.

    Query parameters:
    - start_date: Filter transactions on or after this date (YYYY-MM-DD)
    - end_date: Filter transactions on or before this date (YYYY-MM-DD)
    - account_id: Filter by specific account
    - category_id: Filter by specific category
    - transaction_type: Filter by type (income, expense, or transfer)

    Returns:
        List of transactions with account and category details
    """
    query = db.query(Transaction).filter(Transaction.user_id == current_user.id)

    # Apply filters
    if start_date:
        try:
            start_dt = datetime.fromisoformat(start_date)
            query = query.filter(Transaction.transaction_date >= start_dt)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid start_date format. Use YYYY-MM-DD"
            )

    if end_date:
        try:
            end_dt = datetime.fromisoformat(end_date)
            query = query.filter(Transaction.transaction_date <= end_dt)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid end_date format. Use YYYY-MM-DD"
            )

    if account_id:
        account_ids = [int(x.strip()) for x in account_id.split(",") if x.strip()]
        if len(account_ids) == 1:
            query = query.filter(Transaction.account_id == account_ids[0])
        elif account_ids:
            query = query.filter(Transaction.account_id.in_(account_ids))

    if category_id:
        category_ids = [int(x.strip()) for x in category_id.split(",") if x.strip()]
        if len(category_ids) == 1:
            query = query.filter(Transaction.category_id == category_ids[0])
        elif category_ids:
            query = query.filter(Transaction.category_id.in_(category_ids))

    if transaction_type:
        query = query.filter(Transaction.transaction_type == transaction_type)

    # Order by date descending (most recent first)
    transactions = query.order_by(Transaction.transaction_date.desc()).all()

    # Build response
    result = []
    for txn in transactions:
        account = db.query(Account).filter(Account.id == txn.account_id).first()
        category = db.query(Category).filter(Category.id == txn.category_id).first() if txn.category_id else None

        # Get linked transfer account info if it's a transfer
        transfer_account_name = None
        if txn.transfer_to_account_id:
            transfer_account = db.query(Account).filter(Account.id == txn.transfer_to_account_id).first()
            transfer_account_name = transfer_account.name if transfer_account else None

        result.append({
            "id": txn.id,
            "account_id": txn.account_id,
            "account_name": account.name if account else "Unknown",
            "category_id": txn.category_id,
            "category_name": category.name if category else None,
            "category_color": category.color if category else None,
            "transaction_type": txn.transaction_type,
            "amount": float(txn.amount),
            "description": txn.description,
            "notes": txn.notes,
            "transaction_date": txn.transaction_date.isoformat(),
            "created_at": txn.created_at.isoformat() if txn.created_at else None,
            "transfer_to_account_id": txn.transfer_to_account_id,
            "transfer_to_account_name": transfer_account_name,
            "splitwise_split": txn.splitwise_split or False
        })

    return result


@router.delete("/{transaction_id}")
async def delete_transaction(
    transaction_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Delete a specific transaction.

    Args:
        transaction_id: Transaction ID to delete
        current_user: Authenticated user
        db: Database session

    Returns:
        Success message
    """
    # Verify transaction ownership
    transaction = db.query(Transaction).filter(
        Transaction.id == transaction_id,
        Transaction.user_id == current_user.id
    ).first()

    if not transaction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction not found or you don't have permission to delete it"
        )

    # Delete transaction
    db.delete(transaction)
    db.commit()

    return {"message": "Transaction deleted successfully"}


class TransactionUpdate(BaseModel):
    category_id: Optional[int] = None
    transaction_type: Optional[str] = None


class MergeTransactionsRequest(BaseModel):
    transaction_ids: List[int]
    primary_id: Optional[int] = None


@router.post("/merge")
async def merge_transactions(
    body: MergeTransactionsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Merge multiple transactions into one.

    Keeps the earliest transaction (by date), calculates the net amount
    (income as positive, expense/transfer as negative), updates the kept
    transaction, and deletes the rest.
    """
    if len(body.transaction_ids) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least 2 transaction IDs are required to merge"
        )

    transactions = db.query(Transaction).filter(
        Transaction.id.in_(body.transaction_ids),
        Transaction.user_id == current_user.id
    ).order_by(Transaction.transaction_date.asc()).all()

    if len(transactions) != len(body.transaction_ids):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="One or more transactions not found"
        )

    # Use user-selected primary, or default to earliest by date
    if body.primary_id:
        primary = next((t for t in transactions if t.id == body.primary_id), None)
        if not primary:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="primary_id must be one of the transaction_ids"
            )
    else:
        primary = transactions[0]

    # Calculate net: income = +amount, expense/transfer = -amount
    net = 0.0
    for txn in transactions:
        if txn.transaction_type in ("income", TransactionType.INCOME):
            net += float(txn.amount)
        else:
            net -= float(txn.amount)

    # Update primary transaction with net result
    if net >= 0:
        primary.transaction_type = TransactionType.INCOME
        primary.amount = round(net, 2)
    else:
        primary.transaction_type = TransactionType.EXPENSE
        primary.amount = round(abs(net), 2)

    # Delete the rest
    deleted_ids = []
    for txn in transactions[1:]:
        deleted_ids.append(txn.id)
        db.delete(txn)

    db.commit()
    db.refresh(primary)

    account = db.query(Account).filter(Account.id == primary.account_id).first()
    category = db.query(Category).filter(Category.id == primary.category_id).first() if primary.category_id else None

    return {
        "id": primary.id,
        "account_id": primary.account_id,
        "account_name": account.name if account else "Unknown",
        "category_id": primary.category_id,
        "category_name": category.name if category else None,
        "category_color": category.color if category else None,
        "transaction_type": primary.transaction_type.value if hasattr(primary.transaction_type, 'value') else primary.transaction_type,
        "amount": float(primary.amount),
        "description": primary.description,
        "transaction_date": primary.transaction_date.isoformat(),
        "merged_count": len(transactions),
        "deleted_ids": deleted_ids
    }


@router.patch("/{transaction_id}")
async def update_transaction(
    transaction_id: int,
    body: TransactionUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update mutable fields on a transaction (category_id, transaction_type)."""
    transaction = db.query(Transaction).filter(
        Transaction.id == transaction_id,
        Transaction.user_id == current_user.id
    ).first()

    if not transaction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction not found"
        )

    if body.transaction_type is not None:
        if body.transaction_type not in ("income", "expense", "transfer"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="transaction_type must be one of: income, expense, transfer"
            )
        transaction.transaction_type = body.transaction_type

    if "category_id" in body.model_fields_set:
        transaction.category_id = body.category_id

    db.commit()
    db.refresh(transaction)

    category = db.query(Category).filter(Category.id == transaction.category_id).first() if transaction.category_id else None
    return {
        "id": transaction.id,
        "category_id": transaction.category_id,
        "category_name": category.name if category else None,
        "category_color": category.color if category else None,
        "transaction_type": transaction.transaction_type,
    }


@router.post("/import-csv", response_model=CSVImportResponse)
async def import_csv(
    file: UploadFile = File(...),
    account_id: int = Form(...),
    skip_duplicates: bool = Form(True),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Import transactions from an AMEX CSV file.

    Expected CSV format:
    - Date (MM/DD/YYYY)
    - Description
    - Amount (positive = expense, negative = income)
    - Appears On Your Statement As (optional)
    - Category (optional, auto-created if doesn't exist)

    Args:
        file: CSV file to upload
        account_id: Account ID to associate transactions with
        skip_duplicates: Whether to skip duplicate transactions (default: True)
        current_user: Authenticated user
        db: Database session

    Returns:
        CSVImportResponse: Import summary with statistics and results
    """
    # Validate file type - accept CSV and PDF
    filename_lower = (file.filename or "").lower()
    if not filename_lower.endswith(".csv") and not filename_lower.endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be a CSV (.csv) or PDF (.pdf) file"
        )

    # Validate MIME type
    if file.content_type and file.content_type not in [
        "text/csv",
        "application/csv",
        "application/vnd.ms-excel",
        "application/pdf"
    ]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file type: {file.content_type}. Must be CSV or PDF."
        )

    # Verify account ownership
    account = db.query(Account).filter(
        Account.id == account_id,
        Account.user_id == current_user.id
    ).first()

    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found or you don't have permission to access it"
        )

    # Read file content
    try:
        content = await file.read()

        # Validate file size
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File too large. Maximum size is {MAX_FILE_SIZE / (1024*1024)}MB"
            )

        # Check if file is empty
        if len(content) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File is empty"
            )

        # Decode content
        file_content = content.decode("utf-8")

    except UnicodeDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File encoding error. Please ensure the file is UTF-8 encoded."
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Error reading file: {str(e)}"
        )

    # Parse CSV and create transactions
    try:
        result = parse_amex_csv(
            file_content=file_content,
            user_id=current_user.id,
            account_id=account_id,
            db=db,
            skip_duplicates=skip_duplicates
        )

        return CSVImportResponse(**result)

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing CSV: {str(e)}"
        )


@router.post("/import-csv/preview", response_model=ImportPreviewResponse)
async def preview_csv_import(
    file: UploadFile = File(...),
    account_id: int = Form(...),
    parser_name: str = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Preview CSV import without saving transactions.

    Auto-detects parser if not specified.
    Returns parsed transactions with suggested categories and duplicate detection.

    Args:
        file: CSV file to preview
        account_id: Account ID for transactions
        parser_name: Optional parser name (auto-detect if not provided)
        current_user: Authenticated user
        db: Database session

    Returns:
        ImportPreviewResponse: Preview data with parsed transactions
    """
    # Validate file type - accept CSV and PDF
    filename_lower = (file.filename or "").lower()
    if not filename_lower.endswith(".csv") and not filename_lower.endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be a CSV (.csv) or PDF (.pdf) file"
        )

    # Verify account ownership
    account = db.query(Account).filter(
        Account.id == account_id,
        Account.user_id == current_user.id
    ).first()

    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found or you don't have permission to access it"
        )

    # Read file content
    try:
        content = await file.read()

        # Handle PDF vs CSV differently
        if filename_lower.endswith(".pdf"):
            # PDFs are binary - pass raw bytes
            file_content = content
        else:
            # CSVs are text - decode as UTF-8
            file_content = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CSV file encoding error. Please ensure the file is UTF-8 encoded."
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Error reading file: {str(e)}"
        )

    # Preview import
    import_service = CSVImportService(db, current_user.id)
    preview = import_service.preview_import(file_content, account_id, parser_name)

    if "error" in preview and preview["error"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=preview["error"]
        )

    return ImportPreviewResponse(**preview)


@router.post("/import-csv/confirm", response_model=ImportConfirmResponse)
async def confirm_csv_import(
    request: ImportConfirmRequest = Body(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Confirm and execute CSV import with user-reviewed categories.

    Args:
        request: Import confirmation request with category mappings
        current_user: Authenticated user
        db: Database session

    Returns:
        ImportConfirmResponse: Import summary
    """
    # Verify account ownership
    account = db.query(Account).filter(
        Account.id == request.account_id,
        Account.user_id == current_user.id
    ).first()

    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found or you don't have permission to access it"
        )

    # Execute import
    try:
        # Check if this is a PDF parser (file_content will be base64 encoded)
        file_content = request.file_content
        if request.parser_name and "pdf" in request.parser_name.lower():
            # Decode base64 to bytes for PDF parsers
            try:
                file_content = base64.b64decode(request.file_content)
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Failed to decode PDF content: {str(e)}"
                )

        import_service = CSVImportService(db, current_user.id)
        result = import_service.import_transactions(
            file_content=file_content,
            account_id=request.account_id,
            parser_name=request.parser_name,
            category_mappings=request.category_mappings,
            type_overrides=request.type_overrides,
            skip_duplicates=request.skip_duplicates,
            filename=request.filename
        )

        return ImportConfirmResponse(**result)

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing CSV: {str(e)}"
        )


@router.get("/import-sessions")
async def list_import_sessions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List all import sessions for the current user.

    Returns:
        List of import sessions with statistics
    """
    sessions = db.query(ImportSession).filter(
        ImportSession.user_id == current_user.id
    ).order_by(ImportSession.created_at.desc()).all()

    result = []
    for session in sessions:
        account = db.query(Account).filter(Account.id == session.account_id).first()
        result.append({
            "id": session.id,
            "account_id": session.account_id,
            "account_name": account.name if account else "Unknown",
            "filename": session.filename,
            "parser_type": session.parser_type,
            "status": session.status,
            "total_rows": session.total_rows,
            "created_count": session.created_count,
            "skipped_count": session.skipped_count,
            "error_count": session.error_count,
            "created_at": session.created_at.isoformat()
        })

    return result


@router.get("/import-sessions/{session_id}/transactions")
async def get_import_session_transactions(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get all transactions from a specific import session.

    Args:
        session_id: Import session ID

    Returns:
        List of transactions from the import session
    """
    # Verify session ownership
    session = db.query(ImportSession).filter(
        ImportSession.id == session_id,
        ImportSession.user_id == current_user.id
    ).first()

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Import session not found"
        )

    # Get transactions
    transactions = db.query(Transaction).filter(
        Transaction.import_session_id == session_id
    ).all()

    result = []
    for txn in transactions:
        account = db.query(Account).filter(Account.id == txn.account_id).first()
        result.append({
            "id": txn.id,
            "account_id": txn.account_id,
            "account_name": account.name if account else "Unknown",
            "transaction_type": txn.transaction_type,
            "amount": float(txn.amount),
            "description": txn.description,
            "transaction_date": txn.transaction_date.isoformat(),
            "category_id": txn.category_id,
            "created_at": txn.created_at.isoformat()
        })

    return {
        "session": {
            "id": session.id,
            "filename": session.filename,
            "parser_type": session.parser_type,
            "status": session.status,
            "created_at": session.created_at.isoformat()
        },
        "transactions": result
    }


@router.get("/balance-snapshots")
async def get_balance_snapshots(
    account_id: Optional[int] = Query(None, description="Filter by account ID"),
    start_date: Optional[str] = Query(None, description="Start date filter (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date filter (YYYY-MM-DD)"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get balance snapshots for user's accounts.

    Query parameters:
    - account_id: Filter by specific account
    - start_date: Filter snapshots on or after this date (YYYY-MM-DD)
    - end_date: Filter snapshots on or before this date (YYYY-MM-DD)

    Returns:
        List of balance snapshots with account details
    """
    query = db.query(AccountBalanceSnapshot).filter(
        AccountBalanceSnapshot.user_id == current_user.id
    )

    # Apply filters
    if account_id:
        query = query.filter(AccountBalanceSnapshot.account_id == account_id)

    if start_date:
        try:
            start_dt = datetime.fromisoformat(start_date)
            query = query.filter(AccountBalanceSnapshot.snapshot_date >= start_dt.date())
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid start_date format. Use YYYY-MM-DD"
            )

    if end_date:
        try:
            end_dt = datetime.fromisoformat(end_date)
            query = query.filter(AccountBalanceSnapshot.snapshot_date <= end_dt.date())
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid end_date format. Use YYYY-MM-DD"
            )

    # Order by date descending (most recent first)
    snapshots = query.order_by(AccountBalanceSnapshot.snapshot_date.desc()).all()

    # Build response
    result = []
    for snapshot in snapshots:
        account = db.query(Account).filter(Account.id == snapshot.account_id).first()

        result.append({
            "id": snapshot.id,
            "account_id": snapshot.account_id,
            "account_name": account.name if account else "Unknown",
            "balance": float(snapshot.balance),
            "snapshot_date": snapshot.snapshot_date.isoformat(),
            "snapshot_type": snapshot.snapshot_type,
            "period_year": snapshot.period_year,
            "period_month": snapshot.period_month,
            "created_at": snapshot.created_at.isoformat() if snapshot.created_at else None
        })

    return result
