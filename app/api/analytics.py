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
from app.services.category_expenses_service import CategoryExpensesService
from app.services import household_service

router = APIRouter()


def _resolve_scope_account_ids(db: Session, user_id: int, household_id: Optional[int]) -> list[int]:
    """Resolve account-id set for analytics. Individual scope = visible accounts; household scope = all members' personal + joint accounts."""
    if household_id is None:
        return household_service.get_visible_account_ids(db, user_id)
    household_service.assert_member(db, household_id, user_id)
    return household_service.get_household_account_ids(db, household_id)


@router.get("/sankey")
async def get_sankey_data(
    start_date: Optional[datetime] = Query(None, description="Start date for analysis"),
    end_date: Optional[datetime] = Query(None, description="End date for analysis"),
    include_transfers: bool = Query(False, description="Include account-to-account transfers"),
    household_id: Optional[int] = Query(None, description="If set, scope to a household (combined across members + joint)"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Sankey cash flow. Default scope: caller's visible accounts (personal + any joint they can see).
    With ``household_id``: combined across every member's personal + joint accounts.
    """
    if not end_date:
        end_date = datetime.utcnow()
    if not start_date:
        start_date = end_date - timedelta(days=30)

    account_ids = _resolve_scope_account_ids(db, current_user.id, household_id)
    sankey_service = SankeyService(db)
    return sankey_service.generate_sankey_data(
        account_ids=account_ids,
        start_date=start_date,
        end_date=end_date,
        include_transfers=include_transfers,
    )


@router.get("/dashboard")
async def get_dashboard_summary(
    household_id: Optional[int] = Query(None, description="If set, scope to a household (combined across members + joint)"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Dashboard summary: total balance, this month's income/expenses, recent 10 transactions.
    Default scope: caller's visible accounts. With ``household_id``: full household scope.
    """
    account_ids = _resolve_scope_account_ids(db, current_user.id, household_id)

    if not account_ids:
        empty_period_now = datetime.utcnow()
        return {
            "total_balance": 0.0,
            "month_income": 0.0,
            "month_expenses": 0.0,
            "recent_transactions": [],
            "period": {
                "month_start": datetime(empty_period_now.year, empty_period_now.month, 1).isoformat(),
                "month_end": (
                    datetime(empty_period_now.year + 1, 1, 1)
                    if empty_period_now.month == 12
                    else datetime(empty_period_now.year, empty_period_now.month + 1, 1)
                ).isoformat(),
            },
        }

    # Total balance: sum of current_balance across visible accounts
    total_balance = db.query(func.sum(Account.current_balance)).filter(
        Account.id.in_(account_ids)
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
            Transaction.account_id.in_(account_ids),
            Transaction.transaction_type == 'income',
            Transaction.transaction_date >= month_start,
            Transaction.transaction_date < month_end
        )
    ).scalar() or Decimal('0')

    # Calculate this month's expenses
    month_expenses = db.query(func.sum(Transaction.amount)).filter(
        and_(
            Transaction.account_id.in_(account_ids),
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
        Transaction.account_id.in_(account_ids)
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


@router.get("/category-expenses-monthly")
async def get_category_expenses_monthly(
    year: int = Query(..., description="Year to analyze"),
    household_id: Optional[int] = Query(None, description="If set, scope to a household (combined across members + joint)"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    account_ids = _resolve_scope_account_ids(db, current_user.id, household_id)
    service = CategoryExpensesService(db)
    return service.get_category_expenses_monthly(
        account_ids=account_ids,
        year=year,
    )
