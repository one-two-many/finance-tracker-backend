"""
Self-managed account service.

For accounts flagged ``is_self_managed = True`` the user enters deposits /
withdrawals manually and the system auto-accrues monthly interest using the
rate history in ``account_rate_history``.

Accrual is lazy: call :func:`accrue_account` or :func:`accrue_all_for_user`
before any read path that depends on a current balance (net worth, account
listings, etc.). Writes are idempotent — each monthly accrual transaction is
stamped with a ``raw_data`` marker so re-running skips months already posted.
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
from typing import List, Optional, Tuple

from dateutil.relativedelta import relativedelta
from sqlalchemy.orm import Session

from app.models.account import Account
from app.models.account_rate_history import AccountRateHistory
from app.models.account_balance_snapshot import AccountBalanceSnapshot
from app.models.transaction import Transaction, TransactionType
from app.services.csv_import.legacy import find_or_create_category


_INTEREST_MARKER_KIND = "auto_interest"


def _to_decimal(value) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _first_of_month(d: date) -> date:
    return date(d.year, d.month, 1)


def _last_complete_month(today: date) -> date:
    """Return first-of-month for the most recent *complete* month.

    We accrue a month only once it's finished, so on 2026-04-21 the last
    complete month is 2026-03.
    """
    return _first_of_month(today) - relativedelta(months=1)


def _txn_date(d: date) -> datetime:
    """Transaction.transaction_date is tz-aware; use midnight UTC."""
    return datetime.combine(d, time.min, tzinfo=timezone.utc)


def _rate_for_month(
    history: List[AccountRateHistory], month_start: date
) -> Optional[Decimal]:
    """Pick the rate whose effective_date is the latest value <= month_start."""
    latest: Optional[AccountRateHistory] = None
    for h in history:
        if h.effective_date <= month_start and (
            latest is None or h.effective_date > latest.effective_date
        ):
            latest = h
    return _to_decimal(latest.rate) if latest is not None else None


def _balance_as_of(
    db: Session, account: Account, as_of: date
) -> Decimal:
    """Best balance known at ``as_of``.

    Priority:
    1. Newest snapshot with snapshot_date <= as_of.
    2. initial_balance (seed).
    """
    snap = (
        db.query(AccountBalanceSnapshot)
          .filter(
              AccountBalanceSnapshot.account_id == account.id,
              AccountBalanceSnapshot.snapshot_date <= as_of,
          )
          .order_by(
              AccountBalanceSnapshot.snapshot_date.desc(),
              AccountBalanceSnapshot.id.desc(),
          )
          .first()
    )
    if snap is not None:
        return _to_decimal(snap.balance)
    return _to_decimal(account.initial_balance)


def _last_accrued_month(db: Session, account: Account) -> Optional[date]:
    """Return the first-of-month of the last auto-accrued interest txn, or None."""
    txns = (
        db.query(Transaction)
          .filter(
              Transaction.account_id == account.id,
              Transaction.transaction_type == TransactionType.INCOME,
          )
          .all()
    )
    latest_period: Optional[date] = None
    for t in txns:
        raw = t.raw_data or {}
        if not isinstance(raw, dict):
            continue
        if raw.get("kind") != _INTEREST_MARKER_KIND:
            continue
        period = raw.get("period")
        if not isinstance(period, str) or len(period) != 7:
            continue
        try:
            year, month = int(period[:4]), int(period[5:7])
            period_date = date(year, month, 1)
        except ValueError:
            continue
        if latest_period is None or period_date > latest_period:
            latest_period = period_date
    return latest_period


def _seed_month(account: Account) -> Optional[date]:
    """First month the account can start accruing.

    Uses ``inception_date`` if set, else the ``created_at`` date.
    Returns the first of the month *after* the seed so we never accrue the
    partial month the account was opened.
    """
    seed: Optional[date] = account.inception_date
    if seed is None and account.created_at is not None:
        seed = account.created_at.date() if isinstance(account.created_at, datetime) else account.created_at
    if seed is None:
        return None
    return _first_of_month(seed) + relativedelta(months=1)


def accrue_account(
    db: Session, account: Account, today: Optional[date] = None
) -> List[Transaction]:
    """Post any missing monthly interest transactions for one account.

    Writes but does not commit — caller owns the transaction boundary.
    Returns the list of created Transaction rows (empty if nothing to do).
    """
    if not account.is_self_managed:
        return []

    today = today or date.today()
    end_month = _last_complete_month(today)

    last = _last_accrued_month(db, account)
    if last is not None:
        start_month = last + relativedelta(months=1)
    else:
        start_month = _seed_month(account)
        if start_month is None:
            return []

    if start_month > end_month:
        return []

    rate_rows: List[AccountRateHistory] = (
        db.query(AccountRateHistory)
          .filter(AccountRateHistory.account_id == account.id)
          .order_by(AccountRateHistory.effective_date.asc())
          .all()
    )
    if not rate_rows:
        return []

    interest_category = find_or_create_category(db, account.user_id, "Interest")

    created: List[Transaction] = []
    month = start_month
    while month <= end_month:
        rate = _rate_for_month(rate_rows, month)
        if rate is None or rate <= 0:
            month = month + relativedelta(months=1)
            continue

        balance_before = _balance_as_of(db, account, month - relativedelta(days=1))
        monthly_rate = rate / Decimal(12)
        accrual = (balance_before * monthly_rate).quantize(Decimal("0.01"))

        if accrual <= 0:
            month = month + relativedelta(months=1)
            continue

        period_str = f"{month.year:04d}-{month.month:02d}"

        txn = Transaction(
            user_id=account.user_id,
            account_id=account.id,
            transaction_type=TransactionType.INCOME,
            amount=accrual,
            description=f"Interest – {account.name} ({period_str})",
            transaction_date=_txn_date(month),
            category_id=interest_category.id,
            raw_data={"kind": _INTEREST_MARKER_KIND, "period": period_str, "rate": str(rate)},
        )
        db.add(txn)
        created.append(txn)

        new_balance = (balance_before + accrual).quantize(Decimal("0.01"))
        snapshot = AccountBalanceSnapshot(
            user_id=account.user_id,
            account_id=account.id,
            balance=new_balance,
            snapshot_date=month,
            snapshot_type="manual",
            period_year=month.year,
            period_month=month.month,
        )
        db.add(snapshot)

        account.current_balance = new_balance
        account.updated_at = datetime.now(tz=timezone.utc)

        month = month + relativedelta(months=1)

    return created


def accrue_all_for_user(db: Session, user_id: int, today: Optional[date] = None) -> int:
    """Accrue every self-managed account owned by ``user_id``.

    Commits once at the end. Returns the count of transactions created.
    """
    accounts = (
        db.query(Account)
          .filter(Account.user_id == user_id, Account.is_self_managed.is_(True))
          .all()
    )
    total = 0
    for a in accounts:
        total += len(accrue_account(db, a, today=today))
    if total > 0:
        db.commit()
    return total


def seed_rate_history(
    db: Session,
    account: Account,
    rate: Optional[Decimal],
    effective_date: Optional[date] = None,
) -> Optional[AccountRateHistory]:
    """Insert the initial rate-history row for a freshly self-managed account.

    No-op if rate is None or a row already exists. Does not commit.
    """
    if rate is None:
        return None
    existing = (
        db.query(AccountRateHistory.id)
          .filter(AccountRateHistory.account_id == account.id)
          .first()
    )
    if existing is not None:
        return None

    eff = effective_date or account.inception_date
    if eff is None and account.created_at is not None:
        eff = account.created_at.date() if isinstance(account.created_at, datetime) else account.created_at
    if eff is None:
        eff = date.today()

    row = AccountRateHistory(
        user_id=account.user_id,
        account_id=account.id,
        rate=rate,
        effective_date=eff,
    )
    db.add(row)
    return row


def add_rate_change(
    db: Session,
    account: Account,
    new_rate: Decimal,
    effective_date: date,
    today: Optional[date] = None,
) -> Tuple[AccountRateHistory, List[Transaction]]:
    """Accrue up to the day before ``effective_date`` using the OLD rate,
    then insert the new rate row. Caller commits.

    Returns (new_rate_history_row, txns_created_during_pre_accrual).
    """
    today = today or date.today()
    pre_anchor = min(effective_date - relativedelta(days=1), today)
    created = accrue_account(db, account, today=pre_anchor + relativedelta(days=1))

    row = AccountRateHistory(
        user_id=account.user_id,
        account_id=account.id,
        rate=new_rate,
        effective_date=effective_date,
    )
    db.add(row)
    account.interest_rate = new_rate
    account.updated_at = datetime.now(tz=timezone.utc)
    return row, created
