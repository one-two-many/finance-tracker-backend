"""
Net Worth API router.

Endpoints under ``/net-worth`` (mounted at ``/api/v1`` in ``app/main.py``):
  - GET  /net-worth/current           → NetWorthCurrent
  - GET  /net-worth/history           → List[NetWorthHistoryPoint]
  - GET  /net-worth/goals             → List[SavingsGoalOut]
  - POST /net-worth/goals             → SavingsGoalOut (201)
  - PATCH /net-worth/goals/{goal_id}  → SavingsGoalOut
  - DELETE /net-worth/goals/{goal_id} → {"message": "Goal deleted successfully"} (200)

All endpoints require authentication via ``get_current_user`` and filter by
``current_user.id``. Missing / wrong-owner resources return 404 so we do not
leak resource existence.
"""
from decimal import Decimal
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.core.database import get_db
from app.models.account import Account
from app.models.savings_goal import SavingsGoal
from app.models.user import User
from app.schemas.net_worth import (
    NetWorthCurrent,
    NetWorthHistoryPoint,
    SavingsGoalCreate,
    SavingsGoalOut,
    SavingsGoalUpdate,
)
from app.services.net_worth_service import NetWorthService

router = APIRouter(prefix="/net-worth", tags=["net-worth"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_balance_map(current_nw: NetWorthCurrent) -> dict:
    """Build {account_id: balance} from current_nw.by_type[*].accounts."""
    return {a.id: a.balance for bt in current_nw.by_type for a in bt.accounts}


def _enrich_goal(
    goal: SavingsGoal,
    service: NetWorthService,
    current_nw: NetWorthCurrent,
    history: List[NetWorthHistoryPoint],
    balance_map: dict,
) -> SavingsGoalOut:
    """Compute current_amount / progress_pct / projection for one goal."""
    if goal.account_id is not None:
        current_amount = balance_map.get(goal.account_id, Decimal("0"))
    else:
        current_amount = current_nw.total

    target_amount = Decimal(goal.target_amount)
    if target_amount > 0:
        progress_pct = float(Decimal(current_amount) / target_amount * Decimal(100))
    else:
        progress_pct = 0.0
    if progress_pct < 0.0:
        progress_pct = 0.0

    projection = service.project_target(
        Decimal(current_amount), target_amount, history
    )

    return SavingsGoalOut(
        id=goal.id,
        name=goal.name,
        target_amount=target_amount,
        target_date=goal.target_date,
        account_id=goal.account_id,
        created_at=goal.created_at,
        updated_at=goal.updated_at,
        current_amount=Decimal(current_amount),
        progress_pct=progress_pct,
        projection=projection,
    )


def _account_owned_by(db: Session, account_id: int, user_id: int) -> bool:
    return (
        db.query(Account.id)
          .filter(Account.id == account_id, Account.user_id == user_id)
          .first()
        is not None
    )


# ---------------------------------------------------------------------------
# Net worth summary + history
# ---------------------------------------------------------------------------

@router.get("/current", response_model=NetWorthCurrent)
async def get_current_net_worth(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Current net worth summary — total, breakdown by account type, MoM/YoY
    deltas, and a 24-month sparkline. All data is filtered by user_id inside
    the service.
    """
    service = NetWorthService(db, current_user.id)
    return service.get_current_net_worth()


@router.get("/history", response_model=List[NetWorthHistoryPoint])
async def get_net_worth_history(
    months: int = Query(24, ge=1, le=60),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Monthly net-worth time-series (oldest first). ``months`` must be in [1, 60].
    """
    service = NetWorthService(db, current_user.id)
    return service.get_monthly_history(months=months)


# ---------------------------------------------------------------------------
# Savings goals
# ---------------------------------------------------------------------------

@router.get("/goals", response_model=List[SavingsGoalOut])
async def list_savings_goals(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List the current user's savings goals with enrichment (current_amount,
    progress_pct, projection)."""
    service = NetWorthService(db, current_user.id)
    current_nw = service.get_current_net_worth()
    history = service.get_monthly_history(months=24)
    balance_map = _build_balance_map(current_nw)

    goals = (
        db.query(SavingsGoal)
          .filter(SavingsGoal.user_id == current_user.id)
          .order_by(SavingsGoal.created_at.asc())
          .all()
    )

    return [
        _enrich_goal(g, service, current_nw, history, balance_map) for g in goals
    ]


@router.post(
    "/goals",
    response_model=SavingsGoalOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_savings_goal(
    payload: SavingsGoalCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a savings goal. Returns the enriched goal with projection."""
    # Validation: target_amount > 0 (Pydantic doesn't enforce this alone).
    if payload.target_amount is None or Decimal(payload.target_amount) <= 0:
        raise HTTPException(status_code=400, detail="target_amount must be positive")

    # Validation: if account_id is provided, it must belong to current user.
    if payload.account_id is not None:
        if not _account_owned_by(db, payload.account_id, current_user.id):
            raise HTTPException(status_code=404, detail="Account not found")

    goal = SavingsGoal(
        user_id=current_user.id,
        name=payload.name,
        target_amount=payload.target_amount,
        target_date=payload.target_date,
        account_id=payload.account_id,
    )
    db.add(goal)
    db.commit()
    db.refresh(goal)

    service = NetWorthService(db, current_user.id)
    current_nw = service.get_current_net_worth()
    history = service.get_monthly_history(months=24)
    balance_map = _build_balance_map(current_nw)

    return _enrich_goal(goal, service, current_nw, history, balance_map)


@router.patch("/goals/{goal_id}", response_model=SavingsGoalOut)
async def update_savings_goal(
    goal_id: int,
    payload: SavingsGoalUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Partial update. ``None``/missing fields mean 'unchanged'. v1 does NOT
    support clearing ``account_id`` — to remove the link, DELETE and re-create.
    """
    goal = (
        db.query(SavingsGoal)
          .filter(
              SavingsGoal.id == goal_id,
              SavingsGoal.user_id == current_user.id,
          )
          .first()
    )
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")

    # Validate target_amount if supplied
    if payload.target_amount is not None and Decimal(payload.target_amount) <= 0:
        raise HTTPException(status_code=400, detail="target_amount must be positive")

    # Validate account_id ownership if supplied (non-null)
    if payload.account_id is not None:
        if not _account_owned_by(db, payload.account_id, current_user.id):
            raise HTTPException(status_code=404, detail="Account not found")

    # Apply "None means unchanged" semantics for all four fields.
    if payload.name is not None:
        goal.name = payload.name
    if payload.target_amount is not None:
        goal.target_amount = payload.target_amount
    if payload.target_date is not None:
        goal.target_date = payload.target_date
    if payload.account_id is not None:
        goal.account_id = payload.account_id

    db.commit()
    db.refresh(goal)

    service = NetWorthService(db, current_user.id)
    current_nw = service.get_current_net_worth()
    history = service.get_monthly_history(months=24)
    balance_map = _build_balance_map(current_nw)

    return _enrich_goal(goal, service, current_nw, history, balance_map)


@router.delete("/goals/{goal_id}")
async def delete_savings_goal(
    goal_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a savings goal. Returns 200 + a status message to match the
    existing codebase convention for DELETE handlers."""
    goal = (
        db.query(SavingsGoal)
          .filter(
              SavingsGoal.id == goal_id,
              SavingsGoal.user_id == current_user.id,
          )
          .first()
    )
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")

    db.delete(goal)
    db.commit()

    return {"message": "Goal deleted successfully"}
