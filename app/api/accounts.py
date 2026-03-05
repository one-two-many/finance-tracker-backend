from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
from decimal import Decimal

from app.core.database import get_db
from app.api.dependencies import get_current_user
from app.models.user import User
from app.models.account import Account, AccountType

router = APIRouter()


class AccountCreate(BaseModel):
    name: str
    account_type: AccountType
    currency: str = "USD"
    initial_balance: Decimal = Decimal("0.00")
    default_parser: Optional[str] = None
    bank_name: Optional[str] = None
    account_number_last4: Optional[str] = None

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

    class Config:
        from_attributes = True


class AccountUpdate(BaseModel):
    name: Optional[str] = None
    account_type: Optional[AccountType] = None
    default_parser: Optional[str] = None
    bank_name: Optional[str] = None
    account_number_last4: Optional[str] = None

    class Config:
        use_enum_values = True


@router.get("", response_model=List[AccountResponse])
async def get_accounts(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get all accounts for the authenticated user.
    """
    accounts = db.query(Account).filter(Account.user_id == current_user.id).all()
    return accounts


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

    # Create account
    db_account = Account(
        user_id=current_user.id,
        name=account_data.name,
        account_type=account_data.account_type,
        currency=account_data.currency.upper(),
        initial_balance=account_data.initial_balance,
        current_balance=account_data.initial_balance,
        default_parser=account_data.default_parser,
        bank_name=account_data.bank_name,
        account_number_last4=account_data.account_number_last4
    )
    db.add(db_account)
    db.commit()
    db.refresh(db_account)

    return db_account


@router.patch("/{account_id}", response_model=AccountResponse)
async def update_account(
    account_id: int,
    account_data: AccountUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Update an existing account for the authenticated user.
    """
    # Get account
    account = db.query(Account).filter(
        Account.id == account_id,
        Account.user_id == current_user.id
    ).first()

    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found or you don't have permission to access it"
        )

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

    db.commit()
    db.refresh(account)

    return account


@router.delete("/{account_id}")
async def delete_account(
    account_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Delete an account for the authenticated user.
    Note: This will cascade delete all associated transactions.
    """
    # Get account
    account = db.query(Account).filter(
        Account.id == account_id,
        Account.user_id == current_user.id
    ).first()

    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found or you don't have permission to access it"
        )

    # Delete account (cascade will delete transactions)
    db.delete(account)
    db.commit()

    return {"message": "Account deleted successfully"}
