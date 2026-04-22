"""
Pydantic schemas for the Net Worth feature.

Covers:
- Manual balance entry (§3b) request/response
- Net worth summary + history response shapes
- Savings goal CRUD
"""
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field, ConfigDict


# ---------------------------------------------------------------------------
# Manual balance entry (POST /accounts/{id}/balance-update)
# ---------------------------------------------------------------------------

class ManualBalanceUpdate(BaseModel):
    """Request body for a manual balance update + optional interest entry."""
    balance: Decimal = Field(..., description="Current account value")
    interest_earned: Optional[Decimal] = Field(
        default=None,
        description="If > 0, an INCOME transaction is created and categorized as 'Interest'.",
    )
    as_of_date: Optional[date] = Field(
        default=None,
        description="Snapshot date. Defaults to today on the server side.",
    )
    note: Optional[str] = None


class BalanceSnapshotOut(BaseModel):
    """The snapshot row returned from a manual-balance upsert."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int
    balance: Decimal
    snapshot_date: date
    snapshot_type: str          # always 'manual' here
    period_year: Optional[int] = None
    period_month: Optional[int] = None


class CreatedInterestTxnOut(BaseModel):
    """Summary of the auto-created Interest INCOME transaction (if any)."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    amount: Decimal
    description: str
    transaction_date: datetime
    category_id: Optional[int] = None


class ManualBalanceResponse(BaseModel):
    """Response returned by POST /accounts/{id}/balance-update."""
    snapshot: BalanceSnapshotOut
    interest_transaction: Optional[CreatedInterestTxnOut] = None
    account_current_balance: Decimal


# ---------------------------------------------------------------------------
# Self-managed accounts: deposit / withdraw / rate-change
# ---------------------------------------------------------------------------

class SelfManagedDeposit(BaseModel):
    """Deposit money into a self-managed account."""
    amount: Decimal = Field(..., gt=0, description="Positive amount added to the account.")
    as_of_date: Optional[date] = None
    note: Optional[str] = None


class SelfManagedWithdrawal(BaseModel):
    """Withdraw money from a self-managed account."""
    amount: Decimal = Field(..., gt=0, description="Positive amount removed from the account.")
    as_of_date: Optional[date] = None
    note: Optional[str] = None


class SelfManagedRateChange(BaseModel):
    """Change the APR on a self-managed account from `effective_date` forward."""
    new_rate: Decimal = Field(..., ge=0, description="Annual percentage rate as decimal (e.g. 0.045 = 4.5%).")
    effective_date: date


class RateHistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    rate: Decimal
    effective_date: date
    created_at: datetime


class SelfManagedAdjustmentResponse(BaseModel):
    """Unified response for deposit/withdraw/rate-change.

    `transaction` is null for rate changes; `rate_history` is null for deposits/withdrawals.
    """
    snapshot: Optional[BalanceSnapshotOut] = None
    transaction: Optional[CreatedInterestTxnOut] = None
    rate_history: Optional[RateHistoryOut] = None
    account_current_balance: Decimal
    account_interest_rate: Optional[Decimal] = None


# ---------------------------------------------------------------------------
# GET /net-worth/current
# ---------------------------------------------------------------------------

class AccountSummary(BaseModel):
    """One account's contribution inside a by_type bucket."""
    id: int
    name: str
    balance: Decimal


class AccountTypeTotal(BaseModel):
    """Aggregated total for a single account_type."""
    account_type: str            # 'checking', 'savings', 'credit_card', 'cd', 'high_yield_savings', ...
    total: Decimal               # sign-corrected (liabilities stored as positive absolute value in `total`; net-worth math flips sign)
    is_liability: bool           # True for credit_card
    accounts: List[AccountSummary]


class NetWorthDelta(BaseModel):
    """MoM and YoY deltas. All fields nullable when history is too short."""
    mom_abs: Optional[Decimal] = None
    mom_pct: Optional[float] = None
    yoy_abs: Optional[Decimal] = None
    yoy_pct: Optional[float] = None


class NetWorthCurrent(BaseModel):
    """GET /net-worth/current response."""
    total: Decimal                      # assets − liabilities
    assets: Decimal
    liabilities: Decimal                # positive absolute value
    as_of: date
    by_type: List[AccountTypeTotal]
    delta: NetWorthDelta
    sparkline: List[Decimal]            # up to 24 points, oldest first; values are `net` per month


# ---------------------------------------------------------------------------
# GET /net-worth/history
# ---------------------------------------------------------------------------

class NetWorthHistoryPoint(BaseModel):
    period: str                         # "YYYY-MM"
    assets: Decimal
    liabilities: Decimal
    net: Decimal


# ---------------------------------------------------------------------------
# Savings goals
# ---------------------------------------------------------------------------

class SavingsGoalProjection(BaseModel):
    """Linear-slope projection over last 6 months. All fields may be None."""
    months_to_target: Optional[float] = None
    projected_date: Optional[date] = None
    reason: Optional[str] = None        # e.g., "no positive trend" when slope <= 0


class SavingsGoalCreate(BaseModel):
    name: str = Field(..., max_length=120)
    target_amount: Decimal
    target_date: Optional[date] = None
    account_id: Optional[int] = None


class SavingsGoalUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=120)
    target_amount: Optional[Decimal] = None
    target_date: Optional[date] = None
    account_id: Optional[int] = None


class SavingsGoalOut(BaseModel):
    """GET /net-worth/goals — one row per goal, enriched with current/progress/projection."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    target_amount: Decimal
    target_date: Optional[date] = None
    account_id: Optional[int] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    # Enrichment (computed in the service, not stored in DB):
    current_amount: Decimal             # linked account balance OR total net worth if account_id is null
    progress_pct: float                 # clamped to [0, 100+], no upper cap (user may exceed target)
    projection: SavingsGoalProjection
