from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from datetime import datetime, timedelta
from typing import Optional, List
from decimal import Decimal

from app.core.database import get_db
from app.api.dependencies import get_current_user
from app.models.user import User
from app.models.account import Account
from app.models.transaction import Transaction
from app.models.category import Category
from app.services.sankey_service import SankeyService

router = APIRouter()


@router.get("/sankey")
async def get_sankey_data(
    start_date: Optional[datetime] = Query(None, description="Start date for analysis"),
    end_date: Optional[datetime] = Query(None, description="End date for analysis"),
    include_transfers: bool = Query(False, description="Include account-to-account transfers"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get Sankey diagram data showing money flow:
    Income Sources → Accounts → Expense Categories

    Query Parameters:
        - start_date: Start of analysis period (defaults to 30 days ago)
        - end_date: End of analysis period (defaults to today)
        - include_transfers: Include account-to-account transfers (default: False)

    Returns:
        Sankey diagram data with nodes, links, and summary statistics
    """
    # Default to last 30 days if not provided
    if not end_date:
        end_date = datetime.utcnow()
    if not start_date:
        start_date = end_date - timedelta(days=30)

    # Initialize service and generate data
    sankey_service = SankeyService(db)
    data = sankey_service.generate_sankey_data(
        user_id=current_user.id,
        start_date=start_date,
        end_date=end_date,
        include_transfers=include_transfers
    )

    return data


@router.get("/dashboard")
async def get_dashboard_summary(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get dashboard summary statistics:
    - Total balance across all accounts
    - This month's income
    - This month's expenses
    - Recent transactions (last 10)
    """
    # Calculate total balance from all accounts
    total_balance = db.query(func.sum(Account.current_balance)).filter(
        Account.user_id == current_user.id
    ).scalar() or Decimal('0')

    # Get current month date range
    now = datetime.utcnow()
    month_start = datetime(now.year, now.month, 1)
    if now.month == 12:
        month_end = datetime(now.year + 1, 1, 1)
    else:
        month_end = datetime(now.year, now.month + 1, 1)

    # Calculate this month's income
    month_income = db.query(func.sum(Transaction.amount)).filter(
        and_(
            Transaction.user_id == current_user.id,
            Transaction.transaction_type == 'income',
            Transaction.transaction_date >= month_start,
            Transaction.transaction_date < month_end
        )
    ).scalar() or Decimal('0')

    # Calculate this month's expenses
    month_expenses = db.query(func.sum(Transaction.amount)).filter(
        and_(
            Transaction.user_id == current_user.id,
            Transaction.transaction_type == 'expense',
            Transaction.transaction_date >= month_start,
            Transaction.transaction_date < month_end
        )
    ).scalar() or Decimal('0')

    # Get recent transactions (last 10)
    recent_transactions = db.query(Transaction).join(
        Account, Transaction.account_id == Account.id
    ).outerjoin(
        Category, Transaction.category_id == Category.id
    ).filter(
        Transaction.user_id == current_user.id
    ).order_by(
        Transaction.transaction_date.desc(),
        Transaction.created_at.desc()
    ).limit(10).all()

    # Format recent transactions
    transactions_list = []
    for txn in recent_transactions:
        transactions_list.append({
            "id": txn.id,
            "account_name": txn.account.name,
            "transaction_type": txn.transaction_type,
            "amount": float(txn.amount),
            "description": txn.description,
            "transaction_date": txn.transaction_date.isoformat(),
            "category_name": txn.category.name if txn.category else None,
            "category_color": txn.category.color if txn.category else None,
        })

    return {
        "total_balance": float(total_balance),
        "month_income": float(month_income),
        "month_expenses": float(month_expenses),
        "recent_transactions": transactions_list,
        "period": {
            "month_start": month_start.isoformat(),
            "month_end": month_end.isoformat()
        }
    }
