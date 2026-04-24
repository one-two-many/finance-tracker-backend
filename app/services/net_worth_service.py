"""
Net Worth Service.

Computes current net worth, monthly history, month-over-month / year-over-year
deltas, and linear-slope projections for savings goals.

Balance resolution priority per account (see plan §4):
  1. Latest ``AccountBalanceSnapshot`` — newest ``snapshot_date``; on date tie
     the order is ``manual`` > ``end`` > ``start``.
  2. CDs → ``compute_cd_accrued_value()`` when step 1 returns nothing.
  3. Everything else → ``Account.current_balance`` (legacy fallback).

HYSA never invents a balance: if no snapshot exists, path (3) supplies
``current_balance`` which may be 0 until the user posts a manual update.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional, Tuple

from dateutil.relativedelta import relativedelta
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.account import Account, AccountType
from app.models.account_balance_snapshot import AccountBalanceSnapshot
from app.services import self_managed_service
from app.schemas.net_worth import (
    AccountSummary,
    AccountTypeTotal,
    NetWorthCurrent,
    NetWorthDelta,
    NetWorthHistoryPoint,
    SavingsGoalProjection,
)


# Credit cards are the only liability type supported in v1.
LIABILITY_TYPES = {AccountType.CREDIT_CARD}

# snapshot_type ranking: manual (best) → end → start. Lower number wins.
_SNAPSHOT_RANK = {"manual": 0, "end": 1, "start": 2}


def _to_decimal(value) -> Decimal:
    """Coerce a value (float/str/Decimal/None) to Decimal, defaulting to 0."""
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _months_between(start: date, end: date) -> int:
    """Whole calendar months between two dates (>= 0)."""
    if end <= start:
        return 0
    rd = relativedelta(end, start)
    return rd.years * 12 + rd.months


@dataclass
class _AccountBalance:
    """Resolved balance for a single account at a given date."""
    account: Account
    balance: Decimal


class NetWorthService:
    def __init__(self, db: Session, user_id: int) -> None:
        self.db = db
        self.user_id = user_id

    # ------------------------------------------------------------------
    # CD accrual
    # ------------------------------------------------------------------
    def compute_cd_accrued_value(self, account: Account, as_of: date) -> Decimal:
        """
        Compute the accrued value of a CD using annual compounding.

        Formula:
            elapsed_months = months_between(inception_date, min(as_of, maturity_date))
            capped         = min(elapsed_months, term_months) if term_months else elapsed_months
            accrued        = initial_balance * (1 + interest_rate) ** (capped / 12)

        Annual-compounding simplification per plan open question #1.
        If user confirms monthly/daily compounding later, swap the exponent base.
        """
        initial = _to_decimal(account.initial_balance)
        rate = _to_decimal(account.interest_rate)
        inception = account.inception_date
        maturity = account.maturity_date
        term_months = account.term_months

        if not inception:
            # Without an inception date we cannot accrue; return initial.
            return initial

        upper_bound = as_of
        if maturity and as_of > maturity:
            upper_bound = maturity

        elapsed = _months_between(inception, upper_bound)
        if term_months:
            capped = min(elapsed, term_months)
        else:
            capped = elapsed

        if capped <= 0 or rate <= 0:
            return initial

        exponent = Decimal(capped) / Decimal(12)
        try:
            accrued = initial * (Decimal(1) + rate) ** exponent
        except (InvalidOperation, ValueError):
            return initial
        # Quantize to 2 dp for currency display.
        return accrued.quantize(Decimal("0.01"))

    # ------------------------------------------------------------------
    # Snapshot lookup
    # ------------------------------------------------------------------
    def _latest_snapshot_per_account(self) -> Dict[int, Decimal]:
        """
        Map account_id → latest snapshot balance.

        Ranking when multiple snapshots share the newest date:
        manual > end > start. Otherwise: newest ``snapshot_date`` wins.
        """
        rows = (
            self.db.query(AccountBalanceSnapshot)
            .filter(AccountBalanceSnapshot.user_id == self.user_id)
            .all()
        )

        best: Dict[int, Tuple[date, int, Decimal]] = {}
        for s in rows:
            rank = _SNAPSHOT_RANK.get((s.snapshot_type or "").lower(), 3)
            key = (s.snapshot_date, -rank)  # later date wins; higher "-rank" (less negative) wins tie
            existing = best.get(s.account_id)
            if existing is None or key > (existing[0], -existing[1]):
                best[s.account_id] = (s.snapshot_date, rank, _to_decimal(s.balance))

        return {aid: entry[2] for aid, entry in best.items()}

    # ------------------------------------------------------------------
    # Public: current net worth
    # ------------------------------------------------------------------
    def get_current_net_worth(self) -> NetWorthCurrent:
        today = date.today()
        # Ensure self-managed accounts are caught up before we read balances.
        self_managed_service.accrue_all_for_user(self.db, self.user_id, today=today)

        accounts = (
            self.db.query(Account)
            .filter(Account.user_id == self.user_id)
            .all()
        )

        latest_snapshots = self._latest_snapshot_per_account()

        resolved: List[_AccountBalance] = []
        for acct in accounts:
            if acct.id in latest_snapshots:
                balance = latest_snapshots[acct.id]
            elif acct.account_type == AccountType.CD:
                balance = self.compute_cd_accrued_value(acct, today)
            else:
                balance = _to_decimal(acct.current_balance)
            resolved.append(_AccountBalance(account=acct, balance=balance))

        # Group by account_type, split assets vs liabilities.
        by_type_map: Dict[str, List[_AccountBalance]] = {}
        for rb in resolved:
            key = (
                rb.account.account_type.value
                if isinstance(rb.account.account_type, AccountType)
                else str(rb.account.account_type)
            )
            by_type_map.setdefault(key, []).append(rb)

        by_type: List[AccountTypeTotal] = []
        assets_total = Decimal("0")
        liabilities_total = Decimal("0")
        for type_key, entries in by_type_map.items():
            is_liability = any(
                e.account.account_type == AccountType.CREDIT_CARD for e in entries
            )
            bucket_total = sum((e.balance for e in entries), Decimal("0"))
            # Liabilities stored as positive absolute value in the bucket.
            bucket_total_abs = bucket_total.copy_abs() if is_liability else bucket_total

            if is_liability:
                liabilities_total += bucket_total_abs
            else:
                assets_total += bucket_total

            by_type.append(
                AccountTypeTotal(
                    account_type=type_key,
                    total=bucket_total_abs,
                    is_liability=is_liability,
                    accounts=[
                        AccountSummary(
                            id=e.account.id,
                            name=e.account.name,
                            balance=e.balance.copy_abs() if is_liability else e.balance,
                        )
                        for e in entries
                    ],
                )
            )

        total = assets_total - liabilities_total

        history = self.get_monthly_history(months=24)
        delta = self.get_deltas(history)
        sparkline = [pt.net for pt in history]

        return NetWorthCurrent(
            total=total,
            assets=assets_total,
            liabilities=liabilities_total,
            as_of=today,
            by_type=by_type,
            delta=delta,
            sparkline=sparkline,
        )

    # ------------------------------------------------------------------
    # Public: monthly history
    # ------------------------------------------------------------------
    def get_monthly_history(self, months: int = 24) -> List[NetWorthHistoryPoint]:
        # Self-managed accrual is idempotent — cheap enough to call again here
        # for callers that skip get_current_net_worth().
        self_managed_service.accrue_all_for_user(self.db, self.user_id)

        dialect = self.db.bind.dialect.name if self.db.bind is not None else ""
        if dialect == "sqlite":
            month_totals = self._monthly_non_cd_totals_sqlite(months)
        else:
            month_totals = self._monthly_non_cd_totals_postgres(months)

        # Add CD accrued value per month (CDs excluded from the SQL query).
        cd_accounts = (
            self.db.query(Account)
            .filter(
                Account.user_id == self.user_id,
                Account.account_type == AccountType.CD,
            )
            .all()
        )

        today = date.today()
        first_month = date(today.year, today.month, 1) - relativedelta(months=months - 1)

        result: List[NetWorthHistoryPoint] = []
        for i in range(months):
            month_start = first_month + relativedelta(months=i)
            month_key = (month_start.year, month_start.month)

            assets = Decimal("0")
            liabilities = Decimal("0")

            for (type_key, _year, _month), total in month_totals.items():
                if (_year, _month) != month_key:
                    continue
                is_liability = type_key in {
                    AccountType.CREDIT_CARD.value,
                    "CREDIT_CARD",
                    AccountType.CREDIT_CARD.name,
                }
                if is_liability:
                    liabilities += _to_decimal(total).copy_abs()
                else:
                    assets += _to_decimal(total)

            for cd in cd_accounts:
                # Use the last day of the month as the accrual point so a mid-month
                # CD contributes to its full first month.
                accrual_date = (
                    month_start + relativedelta(months=1) - timedelta(days=1)
                )
                if cd.inception_date and accrual_date < cd.inception_date:
                    continue
                assets += self.compute_cd_accrued_value(cd, accrual_date)

            net = assets - liabilities
            result.append(
                NetWorthHistoryPoint(
                    period=f"{month_start.year:04d}-{month_start.month:02d}",
                    assets=assets,
                    liabilities=liabilities,
                    net=net,
                )
            )

        return result

    def _monthly_non_cd_totals_postgres(
        self, months: int
    ) -> Dict[Tuple[str, int, int], Decimal]:
        """
        Execute the ranked-snapshot forward-fill SQL against PostgreSQL.

        Returns a map (account_type_value, year, month) → total balance.
        """
        offset = months - 1  # generate_series inclusive on both ends
        sql = text(
            f"""
            WITH months AS (
              SELECT generate_series(
                date_trunc('month', now()) - interval '{offset} month',
                date_trunc('month', now()),
                interval '1 month'
              )::date AS month_start
            ),
            ranked AS (
              SELECT s.account_id, s.balance,
                     date_trunc('month', s.snapshot_date)::date AS m,
                     ROW_NUMBER() OVER (
                       PARTITION BY s.account_id, date_trunc('month', s.snapshot_date)
                       ORDER BY CASE s.snapshot_type
                                  WHEN 'manual' THEN 0
                                  WHEN 'end'    THEN 1
                                  ELSE 2 END,
                                s.snapshot_date DESC
                     ) AS rn
              FROM account_balance_snapshots s WHERE s.user_id = :uid
            ),
            per_month AS (SELECT account_id, m, balance FROM ranked WHERE rn = 1),
            grid AS (
              SELECT a.id AS account_id, a.account_type, mo.month_start
              FROM accounts a CROSS JOIN months mo
              WHERE a.user_id = :uid AND a.account_type <> 'CD'
            ),
            ff AS (
              SELECT g.*,
                     (SELECT pm.balance FROM per_month pm
                      WHERE pm.account_id = g.account_id AND pm.m <= g.month_start
                      ORDER BY pm.m DESC LIMIT 1) AS balance
              FROM grid g
            )
            SELECT month_start, account_type, COALESCE(SUM(balance), 0) AS total
            FROM ff GROUP BY month_start, account_type ORDER BY month_start
            """
        )

        rows = self.db.execute(sql, {"uid": self.user_id}).fetchall()

        out: Dict[Tuple[str, int, int], Decimal] = {}
        for r in rows:
            month_start = r[0]
            if isinstance(month_start, datetime):
                month_start = month_start.date()
            account_type_val = r[1]
            if hasattr(account_type_val, "value"):
                type_key = account_type_val.value
            else:
                # Postgres enum returns the enum label as str ("CHECKING" etc.);
                # normalize to AccountType value where we can.
                try:
                    type_key = AccountType[account_type_val].value  # name lookup
                except (KeyError, TypeError):
                    type_key = str(account_type_val)
            total = _to_decimal(r[2])
            out[(type_key, month_start.year, month_start.month)] = total

        return out

    def _monthly_non_cd_totals_sqlite(
        self, months: int
    ) -> Dict[Tuple[str, int, int], Decimal]:
        """
        SQLite dev fallback. Enumerates months in Python and runs a
        ranked-snapshot subquery per (account_id, month_start).
        """
        today = date.today()
        first_month = date(today.year, today.month, 1) - relativedelta(months=months - 1)

        accounts = (
            self.db.query(Account)
            .filter(
                Account.user_id == self.user_id,
                Account.account_type != AccountType.CD,
            )
            .all()
        )

        snapshots = (
            self.db.query(AccountBalanceSnapshot)
            .filter(AccountBalanceSnapshot.user_id == self.user_id)
            .all()
        )

        # Index snapshots by account → list of (snapshot_date, rank, balance).
        per_account: Dict[int, List[Tuple[date, int, Decimal]]] = {}
        for s in snapshots:
            rank = _SNAPSHOT_RANK.get((s.snapshot_type or "").lower(), 3)
            per_account.setdefault(s.account_id, []).append(
                (s.snapshot_date, rank, _to_decimal(s.balance))
            )
        # Sort ascending so the last <=month_start wins forward-fill.
        for lst in per_account.values():
            lst.sort(key=lambda t: (t[0], -t[1]))

        out: Dict[Tuple[str, int, int], Decimal] = {}
        for i in range(months):
            month_start = first_month + relativedelta(months=i)
            for acct in accounts:
                lst = per_account.get(acct.id, [])
                latest: Optional[Decimal] = None
                for snap_date, _rank, bal in lst:
                    if snap_date <= month_start:
                        latest = bal
                    else:
                        break
                if latest is None:
                    continue
                type_key = (
                    acct.account_type.value
                    if isinstance(acct.account_type, AccountType)
                    else str(acct.account_type)
                )
                key = (type_key, month_start.year, month_start.month)
                out[key] = out.get(key, Decimal("0")) + latest
        return out

    # ------------------------------------------------------------------
    # Public: deltas
    # ------------------------------------------------------------------
    def get_deltas(self, history: List[NetWorthHistoryPoint]) -> NetWorthDelta:
        mom_abs: Optional[Decimal] = None
        mom_pct: Optional[float] = None
        yoy_abs: Optional[Decimal] = None
        yoy_pct: Optional[float] = None

        if len(history) >= 2:
            current_net = history[-1].net
            prev_net = history[-2].net
            mom_abs = current_net - prev_net
            if prev_net != 0:
                mom_pct = float(mom_abs / prev_net * Decimal(100))

        if len(history) >= 13:
            current_net = history[-1].net
            year_ago_net = history[-13].net
            yoy_abs = current_net - year_ago_net
            if year_ago_net != 0:
                yoy_pct = float(yoy_abs / year_ago_net * Decimal(100))

        return NetWorthDelta(
            mom_abs=mom_abs,
            mom_pct=mom_pct,
            yoy_abs=yoy_abs,
            yoy_pct=yoy_pct,
        )

    # ------------------------------------------------------------------
    # Public: linear-slope projection
    # ------------------------------------------------------------------
    def project_target(
        self,
        current: Decimal,
        target: Decimal,
        history: List[NetWorthHistoryPoint],
    ) -> SavingsGoalProjection:
        current = _to_decimal(current)
        target = _to_decimal(target)

        if current >= target:
            return SavingsGoalProjection(
                months_to_target=0.0,
                projected_date=date.today(),
                reason=None,
            )

        if len(history) < 7:
            return SavingsGoalProjection(reason="not enough history")

        slope = (history[-1].net - history[-7].net) / Decimal(6)
        if slope <= 0:
            return SavingsGoalProjection(reason="no positive trend")

        months_to_target = float((target - current) / slope)
        projected_date = date.today() + relativedelta(
            months=int(round(months_to_target))
        )
        return SavingsGoalProjection(
            months_to_target=months_to_target,
            projected_date=projected_date,
            reason=None,
        )
