"""
Net Worth API router.

Endpoints under ``/net-worth`` (mounted at ``/api/v1`` in ``app/main.py``).
``/current`` and ``/history`` accept an optional ``household_id`` query param —
when set, results are aggregated across every member's personal + joint accounts.
"""
from collections import defaultdict
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.core.database import get_db
from app.models.account import Account
from app.models.savings_goal import SavingsGoal
from app.models.user import User
from app.schemas.net_worth import (
    AccountSummary,
    AccountTypeTotal,
    NetWorthCurrent,
    NetWorthDelta,
    NetWorthHistoryPoint,
    SavingsGoalCreate,
    SavingsGoalOut,
    SavingsGoalUpdate,
)
from app.services import household_service
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


def _aggregate_current_net_worth(per_member: List[NetWorthCurrent]) -> NetWorthCurrent:
    """Combine multiple per-user NetWorthCurrent payloads into a single household payload."""
    if not per_member:
        return NetWorthCurrent(
            total=Decimal("0"),
            assets=Decimal("0"),
            liabilities=Decimal("0"),
            as_of=__import__("datetime").date.today(),
            by_type=[],
            delta=NetWorthDelta(),
            sparkline=[],
        )

    total = sum((m.total for m in per_member), Decimal("0"))
    assets = sum((m.assets for m in per_member), Decimal("0"))
    liabilities = sum((m.liabilities for m in per_member), Decimal("0"))
    as_of = max(m.as_of for m in per_member)

    # Merge by account_type
    type_buckets: dict[str, AccountTypeTotal] = {}
    for m in per_member:
        for bt in m.by_type:
            existing = type_buckets.get(bt.account_type)
            if existing is None:
                type_buckets[bt.account_type] = AccountTypeTotal(
                    account_type=bt.account_type,
                    total=bt.total,
                    is_liability=bt.is_liability,
                    accounts=list(bt.accounts),
                )
            else:
                existing.total += bt.total
                existing.accounts.extend(bt.accounts)

    # Aligned sparkline: pad shorter members with zeros at the front, sum element-wise
    spark_len = max((len(m.sparkline) for m in per_member), default=0)
    aggregated_sparkline: List[Decimal] = []
    if spark_len:
        padded = []
        for m in per_member:
            pad = [Decimal("0")] * (spark_len - len(m.sparkline))
            padded.append(pad + list(m.sparkline))
        for i in range(spark_len):
            aggregated_sparkline.append(sum((row[i] for row in padded), Decimal("0")))

    return NetWorthCurrent(
        total=total,
        assets=assets,
        liabilities=liabilities,
        as_of=as_of,
        by_type=list(type_buckets.values()),
        delta=NetWorthDelta(),  # household-level deltas are not computed in v1
        sparkline=aggregated_sparkline,
    )


def _aggregate_history(per_member_histories: List[List[NetWorthHistoryPoint]]) -> List[NetWorthHistoryPoint]:
    """Sum monthly histories across members on matching periods."""
    by_period: dict[str, dict[str, Decimal]] = defaultdict(lambda: {"assets": Decimal("0"), "liabilities": Decimal("0"), "net": Decimal("0")})
    for member_history in per_member_histories:
        for point in member_history:
            bucket = by_period[point.period]
            bucket["assets"] += point.assets
            bucket["liabilities"] += point.liabilities
            bucket["net"] += point.net
    return [
        NetWorthHistoryPoint(period=p, assets=v["assets"], liabilities=v["liabilities"], net=v["net"])
        for p, v in sorted(by_period.items())
    ]


# ---------------------------------------------------------------------------
# Net worth summary + history
# ---------------------------------------------------------------------------

@router.get("/current", response_model=NetWorthCurrent)
async def get_current_net_worth(
    household_id: Optional[int] = Query(None, description="If set, return combined networth across the household's members."),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Current net worth — total, breakdown by account type, MoM/YoY deltas, and a
    24-month sparkline. Default scope: the caller. With ``household_id``: summed
    across every member's personal + joint accounts.
    """
    if household_id is None:
        service = NetWorthService(db, current_user.id)
        return service.get_current_net_worth()

    household_service.assert_member(db, household_id, current_user.id)
    member_ids = household_service.get_household_member_user_ids(db, household_id)
    per_member = [NetWorthService(db, uid).get_current_net_worth() for uid in member_ids]
    return _aggregate_current_net_worth(per_member)


@router.get("/history", response_model=List[NetWorthHistoryPoint])
async def get_net_worth_history(
    months: int = Query(24, ge=1, le=60),
    household_id: Optional[int] = Query(None, description="If set, return combined history across the household's members."),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Monthly net-worth time-series (oldest first). ``months`` in [1, 60]. With
    ``household_id``, monthly points are summed across all members.
    """
    if household_id is None:
        service = NetWorthService(db, current_user.id)
        return service.get_monthly_history(months=months)

    household_service.assert_member(db, household_id, current_user.id)
    member_ids = household_service.get_household_member_user_ids(db, household_id)
    per_member = [NetWorthService(db, uid).get_monthly_history(months=months) for uid in member_ids]
    return _aggregate_history(per_member)


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
