from typing import Optional
from fastapi import HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.account import Account
from app.models.household_member import HouseholdMember, HouseholdRole
from app.models.transaction import Transaction


def get_user_household_ids(db: Session, user_id: int) -> list[int]:
    rows = db.query(HouseholdMember.household_id).filter(HouseholdMember.user_id == user_id).all()
    return [r[0] for r in rows]


def get_household_member_user_ids(db: Session, household_id: int) -> list[int]:
    rows = db.query(HouseholdMember.user_id).filter(HouseholdMember.household_id == household_id).all()
    return [r[0] for r in rows]


def get_visible_account_ids(db: Session, user_id: int) -> list[int]:
    """Account IDs the user can see: their personal accounts + joint accounts of any household they belong to."""
    household_ids = get_user_household_ids(db, user_id)
    query = db.query(Account.id).filter(
        or_(
            Account.user_id == user_id,
            Account.household_id.in_(household_ids) if household_ids else False,
        )
    )
    return [r[0] for r in query.all()]


def get_household_account_ids(db: Session, household_id: int) -> list[int]:
    """Every account owned by the household OR by any of its members (personal + joint)."""
    member_ids = get_household_member_user_ids(db, household_id)
    if not member_ids:
        return []
    query = db.query(Account.id).filter(
        or_(
            Account.user_id.in_(member_ids),
            Account.household_id == household_id,
        )
    )
    return [r[0] for r in query.all()]


def get_membership(db: Session, household_id: int, user_id: int) -> Optional[HouseholdMember]:
    return (
        db.query(HouseholdMember)
        .filter(
            HouseholdMember.household_id == household_id,
            HouseholdMember.user_id == user_id,
        )
        .first()
    )


def assert_member(db: Session, household_id: int, user_id: int) -> HouseholdMember:
    membership = get_membership(db, household_id, user_id)
    if membership is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this household")
    return membership


def assert_admin(db: Session, household_id: int, user_id: int) -> HouseholdMember:
    membership = assert_member(db, household_id, user_id)
    if membership.role != HouseholdRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    return membership


def can_modify_account(db: Session, account: Account, user_id: int) -> bool:
    """Personal: only owner. Joint: any admin of the household."""
    if account.household_id is None:
        return account.user_id == user_id
    membership = get_membership(db, account.household_id, user_id)
    return membership is not None and membership.role == HouseholdRole.ADMIN


def can_view_account(db: Session, account: Account, user_id: int) -> bool:
    if account.user_id == user_id:
        return True
    if account.household_id is not None and get_membership(db, account.household_id, user_id) is not None:
        return True
    return False


def can_modify_transaction(db: Session, txn: Transaction, user_id: int) -> bool:
    """Personal txn: only the owner. Joint txn: any household member can modify."""
    account = db.query(Account).filter(Account.id == txn.account_id).first()
    if account is None:
        return False
    if account.household_id is None:
        return txn.user_id == user_id
    return get_membership(db, account.household_id, user_id) is not None
