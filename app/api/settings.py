"""
Settings API Endpoints

Handles user settings including Splitwise integration credentials.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from decimal import Decimal

from app.core.database import get_db
from app.api.dependencies import get_current_user
from app.models.user import User
from app.models.user_settings import UserSettings
from app.models.transaction import Transaction
from app.models.account import Account
from app.services.splitwise_service import SplitwiseService

router = APIRouter()


# Pydantic schemas
class SplitwiseCredentialsUpdate(BaseModel):
    """Request schema for updating Splitwise credentials"""

    api_key: str


class SplitwiseCredentialsResponse(BaseModel):
    """Response schema for Splitwise credential status"""

    is_active: bool
    last_verified_at: Optional[datetime]
    user_info: Optional[dict] = None


class SplitwiseFriend(BaseModel):
    """Schema for Splitwise friend info"""

    id: int
    first_name: str
    last_name: Optional[str] = None
    email: str
    balance: List[dict]


class SplitwiseGroupMember(BaseModel):
    """Schema for a member inside a Splitwise group"""

    id: int
    first_name: str
    last_name: Optional[str] = None
    email: Optional[str] = None


class SplitwiseGroup(BaseModel):
    """Schema for Splitwise group info"""

    id: int
    name: str
    members: List[SplitwiseGroupMember]


class SplitwiseExpenseCreate(BaseModel):
    """Request schema for creating Splitwise expenses"""

    transaction_ids: List[int]
    split_type: str  # "equal", "exact", "percent"
    participants: List[dict]  # [{"user_id": 123, "owed_share": 25.00}]
    group_id: Optional[int] = None
    description: Optional[str] = None  # Custom expense name (defaults to category or descriptions)


# API Endpoints


@router.get("/splitwise/credentials", response_model=SplitwiseCredentialsResponse)
async def get_splitwise_credentials(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """
    Get Splitwise credential status without revealing the API key.

    Returns:
        SplitwiseCredentialsResponse with is_active status and last verification time
    """
    settings = (
        db.query(UserSettings).filter(UserSettings.user_id == current_user.id).first()
    )

    if not settings or not settings.splitwise_api_key:
        return SplitwiseCredentialsResponse(
            is_active=False, last_verified_at=None, user_info=None
        )

    return SplitwiseCredentialsResponse(
        is_active=settings.splitwise_is_active,
        last_verified_at=settings.splitwise_last_verified_at,
        user_info=None,
    )


@router.post("/splitwise/credentials", response_model=SplitwiseCredentialsResponse)
async def update_splitwise_credentials(
    credentials: SplitwiseCredentialsUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Save and verify Splitwise API credentials.

    Tests the API key by calling Splitwise API before saving.
    Stores encrypted API key in database if valid.

    Args:
        credentials: SplitwiseCredentialsUpdate with api_key

    Returns:
        SplitwiseCredentialsResponse with verification status and user info

    Raises:
        HTTPException: If API key is invalid (400)
    """
    # Get or create settings record
    settings = (
        db.query(UserSettings).filter(UserSettings.user_id == current_user.id).first()
    )

    if not settings:
        settings = UserSettings(user_id=current_user.id)
        db.add(settings)

    # Test credentials before saving
    try:
        service = SplitwiseService(credentials.api_key)
        user_info = service.get_current_user()
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"Invalid Splitwise API key: {str(e)}"
        )

    # Save encrypted credentials
    settings.splitwise_api_key = credentials.api_key
    settings.splitwise_is_active = True
    settings.splitwise_last_verified_at = datetime.utcnow()

    db.commit()
    db.refresh(settings)

    return SplitwiseCredentialsResponse(
        is_active=True,
        last_verified_at=settings.splitwise_last_verified_at,
        user_info=user_info,
    )


@router.delete("/splitwise/credentials")
async def delete_splitwise_credentials(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """
    Remove Splitwise credentials from database.

    Returns:
        Success message
    """
    settings = (
        db.query(UserSettings).filter(UserSettings.user_id == current_user.id).first()
    )

    if settings:
        settings.splitwise_api_key = None
        settings.splitwise_is_active = False
        db.commit()

    return {"message": "Splitwise credentials removed"}


@router.get("/splitwise/friends")
async def get_splitwise_friends(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> List[SplitwiseFriend]:
    """
    Get list of Splitwise friends for the authenticated user.

    Returns:
        List of SplitwiseFriend objects

    Raises:
        HTTPException: If Splitwise not connected (400) or API call fails (500)
    """
    settings = (
        db.query(UserSettings).filter(UserSettings.user_id == current_user.id).first()
    )

    if not settings or not settings.splitwise_api_key:
        raise HTTPException(status_code=400, detail="Splitwise not connected")

    try:
        service = SplitwiseService(settings.splitwise_api_key)
        friends = service.get_friends()
        return friends
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch Splitwise friends: {str(e)}"
        )


@router.get("/splitwise/groups")
async def get_splitwise_groups(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> List[SplitwiseGroup]:
    """
    Get list of Splitwise groups the authenticated user belongs to.

    Returns:
        List of SplitwiseGroup objects with member details

    Raises:
        HTTPException: If Splitwise not connected (400) or API call fails (500)
    """
    settings = (
        db.query(UserSettings).filter(UserSettings.user_id == current_user.id).first()
    )

    if not settings or not settings.splitwise_api_key:
        raise HTTPException(status_code=400, detail="Splitwise not connected")

    try:
        service = SplitwiseService(settings.splitwise_api_key)
        groups = service.get_groups()
        return groups
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch Splitwise groups: {str(e)}"
        )


@router.post("/splitwise/expenses")
async def create_splitwise_expenses(
    request: SplitwiseExpenseCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Create Splitwise expenses from selected Finance Tracker transactions.

    Pushes expense transactions to Splitwise with the specified split configuration.
    This is a one-way sync - we don't track split status locally.

    Args:
        request: SplitwiseExpenseCreate with transaction_ids, split_type, and participants

    Returns:
        Dict with total, successful, failed counts and detailed results

    Raises:
        HTTPException: If Splitwise not connected (400) or no valid transactions (404)
    """
    # Get settings
    settings = (
        db.query(UserSettings).filter(UserSettings.user_id == current_user.id).first()
    )

    if not settings or not settings.splitwise_api_key:
        raise HTTPException(status_code=400, detail="Splitwise not connected")

    # Fetch transactions (only expenses owned by user)
    transactions = (
        db.query(Transaction)
        .join(Account, Transaction.account_id == Account.id)
        .filter(
            Transaction.id.in_(request.transaction_ids),
            Transaction.user_id == current_user.id,
            Transaction.transaction_type == "expense",
        )
        .all()
    )

    if not transactions:
        raise HTTPException(
            status_code=404, detail="No valid expense transactions found"
        )

    # Create Splitwise service
    service = SplitwiseService(settings.splitwise_api_key)

    # Get the current user's Splitwise ID — they must be included in every expense
    try:
        sw_user = service.get_current_user()
        sw_user_id = sw_user["id"]
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get Splitwise user info: {str(e)}"
        )

    # Group all selected transactions into ONE Splitwise expense
    total_amount = sum(float(t.amount) for t in transactions)

    # Use custom description from request, or fall back to joined descriptions
    expense_description = request.description
    if not expense_description:
        expense_description = "; ".join(t.description for t in transactions)

    # Build notes from individual transaction details
    notes_parts = []
    for txn in transactions:
        notes_parts.append(f"{txn.description}: ${float(txn.amount):.2f}")
    expense_notes = "\n".join(notes_parts)

    # Currency from first transaction's account
    currency = transactions[0].account.currency or "USD"

    # Build participants — skip current user from request list, add them explicitly
    friends_owed_sum = 0.0
    final_participants = []
    for p in request.participants:
        if p["user_id"] == sw_user_id:
            continue
        owed = round(float(p["owed_share"]), 2)
        friends_owed_sum += owed
        final_participants.append({
            "user_id": p["user_id"],
            "owed_share": owed,
            "paid_share": 0,
        })

    # Current user pays the full cost and owes the remainder
    current_user_owed = round(total_amount - friends_owed_sum, 2)
    final_participants.append({
        "user_id": sw_user_id,
        "owed_share": current_user_owed,
        "paid_share": total_amount,
    })

    try:
        expense_result = service.create_expense(
            description=expense_description,
            amount=Decimal(str(total_amount)),
            currency=currency,
            date=datetime.utcnow(),
            split_type=request.split_type,
            participants=final_participants,
            notes=expense_notes,
            group_id=request.group_id,
        )

        # Mark all transactions as split in our DB
        for txn in transactions:
            txn.splitwise_split = True
        db.commit()

        results = [
            {
                "transaction_id": txn.id,
                "status": "success",
                "splitwise_id": expense_result["id"],
                "url": expense_result["url"],
            }
            for txn in transactions
        ]

        return {
            "total": len(transactions),
            "successful": len(transactions),
            "failed": 0,
            "results": results,
        }
    except Exception as e:
        error_msg = str(e)
        results = [
            {"transaction_id": txn.id, "status": "error", "error": error_msg}
            for txn in transactions
        ]
        return {
            "total": len(transactions),
            "successful": 0,
            "failed": len(transactions),
            "results": results,
        }
