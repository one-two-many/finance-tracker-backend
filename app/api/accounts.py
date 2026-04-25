from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func as sa_func, or_
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Dict, List, Optional
from datetime import datetime, date, time, timezone
from decimal import Decimal

from app.core.database import get_db
from app.api.dependencies import get_current_user
from app.models.user import User
from app.models.account import Account, AccountType
from app.models.account_balance_snapshot import AccountBalanceSnapshot
from app.models.household import Household
from app.models.transaction import Transaction, TransactionType
from app.schemas.net_worth import (
    ManualBalanceUpdate,
    ManualBalanceResponse,
    BalanceSnapshotOut,
    CreatedInterestTxnOut,
    SelfManagedDeposit,
    SelfManagedWithdrawal,
    SelfManagedRateChange,
    SelfManagedAdjustmentResponse,
    RateHistoryOut,
)
from app.services.csv_import.legacy import find_or_create_category
from app.services import self_managed_service, household_service

router = APIRouter()


class AccountCreate(BaseModel):
    name: str
    account_type: AccountType
    currency: str = "USD"
    initial_balance: Decimal = Decimal("0.00")
    default_parser: Optional[str] = None
    bank_name: Optional[str] = None
    account_number_last4: Optional[str] = None
    household_id: Optional[int] = None          # set when account is joint (shared with household)
    # CD + HYSA support
    interest_rate: Optional[Decimal] = None     # e.g. 0.0450 for 4.5% APR (HYSA: reference only; CD: used in accrual formula)
    maturity_date: Optional[date] = None        # CD only
    term_months: Optional[int] = None           # CD only
    inception_date: Optional[date] = None       # CD only (account open date)
    is_self_managed: bool = False               # user enters balance changes manually, system auto-accrues interest

    class Config:
        use_enum_values = True


class AccountResponse(BaseModel):
    id: int
    name: str
    account_type: str
    currency: str
    current_balance: Decimal
    default_parser: Optional[str] = None
    bank_name: Optional[str] = None
    account_number_last4: Optional[str] = None
    created_at: datetime
    # CD + HYSA support
    interest_rate: Optional[Decimal] = None
    maturity_date: Optional[date] = None
    term_months: Optional[int] = None
    inception_date: Optional[date] = None
    is_self_managed: bool = False
    # Derived: latest date the balance is known to be correct.
    # Self-managed → max(snapshot.snapshot_date); parser-backed → max(transaction.transaction_date).
    # Credit cards intentionally omitted (statement-driven, not balance-driven).
    balance_as_of_date: Optional[date] = None
    # Household / shared-ownership info
    household_id: Optional[int] = None
    household_name: Optional[str] = None
    creator_user_id: Optional[int] = None
    creator_username: Optional[str] = None

    class Config:
        from_attributes = True


class AccountUpdate(BaseModel):
    name: Optional[str] = None
    account_type: Optional[AccountType] = None
    default_parser: Optional[str] = None
    bank_name: Optional[str] = None
    account_number_last4: Optional[str] = None
    household_id: Optional[int] = None          # change ownership: int = move to household, 0 = make personal
    # CD + HYSA support (all optional — None means "leave unchanged")
    interest_rate: Optional[Decimal] = None
    maturity_date: Optional[date] = None
    term_months: Optional[int] = None
    inception_date: Optional[date] = None
    is_self_managed: Optional[bool] = None

    class Config:
        use_enum_values = True


def _enrich_account_response(db: Session, account: Account, balance_as_of: Optional[date]) -> AccountResponse:
    household_name = None
    if account.household_id is not None:
        h = db.query(Household).filter(Household.id == account.household_id).first()
        household_name = h.name if h is not None else None
    creator = db.query(User).filter(User.id == account.user_id).first()
    return AccountResponse.model_validate(account).model_copy(
        update={
            "balance_as_of_date": balance_as_of,
            "household_id": account.household_id,
            "household_name": household_name,
            "creator_user_id": account.user_id,
            "creator_username": creator.username if creator is not None else None,
        }
    )


@router.get("", response_model=List[AccountResponse])
async def get_accounts(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get all accounts for the authenticated user.

    Before returning, lazily accrues monthly interest on self-managed accounts
    so the listed balance reflects all complete months. Each non-credit-card
    account also carries a derived ``balance_as_of_date`` — the latest date we
    have evidence the balance is correct (max snapshot for self-managed, max
    transaction date for parser-backed).
    """
    # Keep self-managed balances current before we read them.
    self_managed_service.accrue_all_for_user(db, current_user.id)

    household_ids = household_service.get_user_household_ids(db, current_user.id)
    if household_ids:
        accounts = (
            db.query(Account)
            .filter(or_(Account.user_id == current_user.id, Account.household_id.in_(household_ids)))
            .all()
        )
    else:
        accounts = db.query(Account).filter(Account.user_id == current_user.id).all()

    balance_as_of: Dict[int, Optional[date]] = {}
    if accounts:
        account_ids = [a.id for a in accounts]

        max_txn_dates: Dict[int, date] = dict(
            db.query(
                Transaction.account_id,
                sa_func.max(sa_func.date(Transaction.transaction_date)),
            )
            .filter(Transaction.account_id.in_(account_ids))
            .group_by(Transaction.account_id)
            .all()
        )
        max_snap_dates: Dict[int, date] = dict(
            db.query(
                AccountBalanceSnapshot.account_id,
                sa_func.max(AccountBalanceSnapshot.snapshot_date),
            )
            .filter(AccountBalanceSnapshot.account_id.in_(account_ids))
            .group_by(AccountBalanceSnapshot.account_id)
            .all()
        )

        for a in accounts:
            if a.account_type == AccountType.CREDIT_CARD:
                balance_as_of[a.id] = None
                continue
            if a.is_self_managed:
                as_of = max_snap_dates.get(a.id) or max_txn_dates.get(a.id)
            else:
                as_of = max_txn_dates.get(a.id)
            if as_of is None and a.created_at is not None:
                as_of = (
                    a.created_at.date()
                    if isinstance(a.created_at, datetime)
                    else a.created_at
                )
            balance_as_of[a.id] = as_of

    return [_enrich_account_response(db, a, balance_as_of.get(a.id)) for a in accounts]


@router.post("", response_model=AccountResponse, status_code=status.HTTP_201_CREATED)
async def create_account(
    account_data: AccountCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create a new account for the authenticated user.
    """
    # Validate currency code (basic check)
    if len(account_data.currency) != 3:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Currency code must be 3 characters (e.g., USD, EUR, GBP)"
        )

    # If joint, verify the user is a member of the chosen household
    if account_data.household_id is not None:
        household_service.assert_member(db, account_data.household_id, current_user.id)

    # Create account
    db_account = Account(
        user_id=current_user.id,
        household_id=account_data.household_id,
        name=account_data.name,
        account_type=account_data.account_type,
        currency=account_data.currency.upper(),
        initial_balance=account_data.initial_balance,
        current_balance=account_data.initial_balance,
        default_parser=account_data.default_parser,
        bank_name=account_data.bank_name,
        account_number_last4=account_data.account_number_last4,
        interest_rate=account_data.interest_rate,
        maturity_date=account_data.maturity_date,
        term_months=account_data.term_months,
        inception_date=account_data.inception_date,
        is_self_managed=account_data.is_self_managed,
    )
    db.add(db_account)
    db.flush()

    if db_account.is_self_managed:
        self_managed_service.seed_rate_history(
            db, db_account, account_data.interest_rate, account_data.inception_date
        )

    db.commit()
    db.refresh(db_account)

    return _enrich_account_response(db, db_account, None)


@router.patch("/{account_id}", response_model=AccountResponse)
async def update_account(
    account_id: int,
    account_data: AccountUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Update an existing account. Personal accounts may be edited by their owner; joint
    accounts may be edited by any admin of the household.
    """
    account = db.query(Account).filter(Account.id == account_id).first()
    if account is None or not household_service.can_view_account(db, account, current_user.id):
        raise HTTPException(status_code=404, detail="Account not found")
    if not household_service.can_modify_account(db, account, current_user.id):
        raise HTTPException(status_code=403, detail="You don't have permission to modify this account")

    # Update fields
    if account_data.name is not None:
        account.name = account_data.name
    if account_data.account_type is not None:
        account.account_type = account_data.account_type
    if account_data.default_parser is not None:
        account.default_parser = account_data.default_parser
    if account_data.bank_name is not None:
        account.bank_name = account_data.bank_name
    if account_data.account_number_last4 is not None:
        account.account_number_last4 = account_data.account_number_last4
    if "household_id" in account_data.model_fields_set:
        new_hid = account_data.household_id
        if new_hid in (None, 0):
            account.household_id = None
        else:
            household_service.assert_admin(db, new_hid, current_user.id)
            account.household_id = new_hid
    if account_data.interest_rate is not None:
        account.interest_rate = account_data.interest_rate
    if account_data.maturity_date is not None:
        account.maturity_date = account_data.maturity_date
    if account_data.term_months is not None:
        account.term_months = account_data.term_months
    if account_data.inception_date is not None:
        account.inception_date = account_data.inception_date

    was_self_managed = account.is_self_managed
    if account_data.is_self_managed is not None:
        account.is_self_managed = account_data.is_self_managed

    db.flush()

    if not was_self_managed and account.is_self_managed:
        self_managed_service.seed_rate_history(
            db, account, account.interest_rate, account.inception_date
        )

    db.commit()
    db.refresh(account)

    return _enrich_account_response(db, account, None)


@router.delete("/{account_id}")
async def delete_account(
    account_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Delete an account. Personal accounts: owner only. Joint accounts: admin of the household.
    Cascade-deletes all associated transactions.
    """
    account = db.query(Account).filter(Account.id == account_id).first()
    if account is None or not household_service.can_view_account(db, account, current_user.id):
        raise HTTPException(status_code=404, detail="Account not found")
    if not household_service.can_modify_account(db, account, current_user.id):
        raise HTTPException(status_code=403, detail="You don't have permission to delete this account")

    db.delete(account)
    db.commit()

    return {"message": "Account deleted successfully"}


@router.post("/{account_id}/balance-update", response_model=ManualBalanceResponse)
async def update_account_balance(
    account_id: int,
    payload: ManualBalanceUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Manual balance entry for HYSA, CD, investments, or any account without an
    auto-populating parser. Upserts an AccountBalanceSnapshot for the given
    as_of_date (defaults to today), updates Account.current_balance, and
    optionally creates an Interest INCOME transaction.

    Returns 200 OK (upsert semantics).
    """
    # Ownership check (joint accounts: admins only)
    account = db.query(Account).filter(Account.id == account_id).first()
    if account is None or not household_service.can_view_account(db, account, current_user.id):
        raise HTTPException(status_code=404, detail="Account not found")
    if not household_service.can_modify_account(db, account, current_user.id):
        raise HTTPException(status_code=403, detail="You don't have permission to update this account's balance")

    # Validate interest_earned sign before any writes
    if payload.interest_earned is not None and payload.interest_earned < 0:
        raise HTTPException(status_code=400, detail="interest_earned must be positive")

    as_of = payload.as_of_date or date.today()

    # Upsert snapshot on (user_id, account_id, snapshot_date=as_of, snapshot_type='manual')
    snapshot = (
        db.query(AccountBalanceSnapshot)
          .filter(
              AccountBalanceSnapshot.user_id == current_user.id,
              AccountBalanceSnapshot.account_id == account_id,
              AccountBalanceSnapshot.snapshot_date == as_of,
              AccountBalanceSnapshot.snapshot_type == "manual",
          )
          .first()
    )
    if snapshot is not None:
        snapshot.balance = payload.balance
        snapshot.period_year = as_of.year
        snapshot.period_month = as_of.month
    else:
        snapshot = AccountBalanceSnapshot(
            user_id=current_user.id,
            account_id=account_id,
            balance=payload.balance,
            snapshot_date=as_of,
            snapshot_type="manual",
            period_year=as_of.year,
            period_month=as_of.month,
        )
        db.add(snapshot)

    # Always overwrite account.current_balance and updated_at (tz-aware column).
    account.current_balance = payload.balance
    account.updated_at = datetime.now(tz=timezone.utc)

    # Optional interest INCOME transaction
    interest_txn: Optional[Transaction] = None
    if payload.interest_earned is not None and payload.interest_earned > 0:
        interest_category = find_or_create_category(db, current_user.id, "Interest")

        # Transaction.transaction_date is DateTime(timezone=True). Combine as_of with
        # midnight UTC.
        txn_dt = datetime.combine(as_of, time.min, tzinfo=timezone.utc)

        interest_txn = Transaction(
            user_id=current_user.id,
            account_id=account.id,
            transaction_type=TransactionType.INCOME,
            amount=payload.interest_earned,
            description=f"Interest – {account.name}",  # en-dash U+2013
            transaction_date=txn_dt,
            category_id=interest_category.id,
            notes=payload.note,
        )
        db.add(interest_txn)

    # Single commit covers snapshot upsert, account update, and optional interest txn.
    db.commit()
    db.refresh(snapshot)
    db.refresh(account)
    if interest_txn is not None:
        db.refresh(interest_txn)

    return ManualBalanceResponse(
        snapshot=BalanceSnapshotOut.model_validate(snapshot),
        interest_transaction=(
            CreatedInterestTxnOut.model_validate(interest_txn)
            if interest_txn is not None
            else None
        ),
        account_current_balance=account.current_balance,
    )


# ---------------------------------------------------------------------------
# Self-managed account adjustments
# ---------------------------------------------------------------------------

def _require_self_managed(
    db: Session, account_id: int, user_id: int
) -> Account:
    account = db.query(Account).filter(Account.id == account_id).first()
    if account is None or not household_service.can_view_account(db, account, user_id):
        raise HTTPException(status_code=404, detail="Account not found")
    if not household_service.can_modify_account(db, account, user_id):
        raise HTTPException(status_code=403, detail="You don't have permission to modify this account")
    if not account.is_self_managed:
        raise HTTPException(
            status_code=400,
            detail="Account is not self-managed; use CSV import or /balance-update instead.",
        )
    return account


def _record_adjustment(
    db: Session,
    account: Account,
    *,
    amount: Decimal,
    kind: str,  # "deposit" or "withdraw"
    as_of: date,
    note: Optional[str],
) -> tuple[Transaction, AccountBalanceSnapshot]:
    """Accrue interest up to today, then post deposit/withdrawal txn + snapshot.

    The accrual keeps monthly interest current before we mutate the balance.
    """
    self_managed_service.accrue_account(db, account)

    signed = amount if kind == "deposit" else -amount
    new_balance = (Decimal(account.current_balance) + signed).quantize(Decimal("0.01"))

    txn_type = TransactionType.INCOME if kind == "deposit" else TransactionType.EXPENSE
    description = (
        f"Deposit – {account.name}" if kind == "deposit" else f"Withdrawal – {account.name}"
    )

    txn = Transaction(
        user_id=account.user_id,
        account_id=account.id,
        transaction_type=txn_type,
        amount=amount,
        description=description,
        transaction_date=datetime.combine(as_of, time.min, tzinfo=timezone.utc),
        notes=note,
        raw_data={"kind": f"self_managed_{kind}"},
    )
    db.add(txn)

    snapshot = AccountBalanceSnapshot(
        user_id=account.user_id,
        account_id=account.id,
        balance=new_balance,
        snapshot_date=as_of,
        snapshot_type="manual",
        period_year=as_of.year,
        period_month=as_of.month,
    )
    db.add(snapshot)

    account.current_balance = new_balance
    account.updated_at = datetime.now(tz=timezone.utc)
    return txn, snapshot


@router.post(
    "/{account_id}/deposit",
    response_model=SelfManagedAdjustmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def self_managed_deposit(
    account_id: int,
    payload: SelfManagedDeposit,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Add money to a self-managed account."""
    account = _require_self_managed(db, account_id, current_user.id)
    as_of = payload.as_of_date or date.today()
    txn, snap = _record_adjustment(
        db, account, amount=payload.amount, kind="deposit", as_of=as_of, note=payload.note
    )
    db.commit()
    db.refresh(account)
    db.refresh(txn)
    db.refresh(snap)

    return SelfManagedAdjustmentResponse(
        snapshot=BalanceSnapshotOut.model_validate(snap),
        transaction=CreatedInterestTxnOut.model_validate(txn),
        rate_history=None,
        account_current_balance=account.current_balance,
        account_interest_rate=account.interest_rate,
    )


@router.post(
    "/{account_id}/withdraw",
    response_model=SelfManagedAdjustmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def self_managed_withdraw(
    account_id: int,
    payload: SelfManagedWithdrawal,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove money from a self-managed account."""
    account = _require_self_managed(db, account_id, current_user.id)
    as_of = payload.as_of_date or date.today()
    txn, snap = _record_adjustment(
        db, account, amount=payload.amount, kind="withdraw", as_of=as_of, note=payload.note
    )
    db.commit()
    db.refresh(account)
    db.refresh(txn)
    db.refresh(snap)

    return SelfManagedAdjustmentResponse(
        snapshot=BalanceSnapshotOut.model_validate(snap),
        transaction=CreatedInterestTxnOut.model_validate(txn),
        rate_history=None,
        account_current_balance=account.current_balance,
        account_interest_rate=account.interest_rate,
    )


@router.post(
    "/{account_id}/rate-change",
    response_model=SelfManagedAdjustmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def self_managed_rate_change(
    account_id: int,
    payload: SelfManagedRateChange,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update the APR on a self-managed account from `effective_date` forward.
    Accrues using the old rate up to the day before `effective_date`, then
    switches to the new rate. Past accruals are never recomputed.
    """
    account = _require_self_managed(db, account_id, current_user.id)

    row, _created = self_managed_service.add_rate_change(
        db, account, payload.new_rate, payload.effective_date
    )
    db.commit()
    db.refresh(row)
    db.refresh(account)

    return SelfManagedAdjustmentResponse(
        snapshot=None,
        transaction=None,
        rate_history=RateHistoryOut.model_validate(row),
        account_current_balance=account.current_balance,
        account_interest_rate=account.interest_rate,
    )


@router.get(
    "/{account_id}/rate-history",
    response_model=List[RateHistoryOut],
)
async def list_rate_history(
    account_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List rate history for a self-managed account (oldest first)."""
    account = db.query(Account).filter(Account.id == account_id).first()
    if account is None or not household_service.can_view_account(db, account, current_user.id):
        raise HTTPException(status_code=404, detail="Account not found")

    from app.models.account_rate_history import AccountRateHistory
    rows = (
        db.query(AccountRateHistory)
          .filter(AccountRateHistory.account_id == account_id)
          .order_by(AccountRateHistory.effective_date.asc())
          .all()
    )
    return rows
