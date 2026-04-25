from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import or_, func as sa_func
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.core.database import get_db
from app.models.household import Household
from app.models.household_invitation import HouseholdInvitation, InvitationStatus
from app.models.household_member import HouseholdMember, HouseholdRole
from app.models.user import User
from app.services import household_service

router = APIRouter()


# ----- Schemas ---------------------------------------------------------------

class HouseholdCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class HouseholdRename(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class InviteRequest(BaseModel):
    email_or_username: str = Field(min_length=1)


class HouseholdSummary(BaseModel):
    id: int
    name: str
    role: HouseholdRole
    member_count: int
    created_at: datetime


class MemberOut(BaseModel):
    user_id: int
    username: str
    email: str
    role: HouseholdRole
    joined_at: datetime


class HouseholdDetail(BaseModel):
    id: int
    name: str
    role: HouseholdRole
    members: list[MemberOut]
    created_at: datetime


class InvitationOut(BaseModel):
    id: int
    household_id: int
    household_name: str
    inviter_user_id: int
    inviter_username: str
    invitee_user_id: int
    status: InvitationStatus
    created_at: datetime
    responded_at: Optional[datetime] = None


# ----- Helpers ---------------------------------------------------------------

def _household_summary(db: Session, household: Household, role: HouseholdRole) -> HouseholdSummary:
    member_count = (
        db.query(sa_func.count(HouseholdMember.id))
        .filter(HouseholdMember.household_id == household.id)
        .scalar()
        or 0
    )
    return HouseholdSummary(
        id=household.id,
        name=household.name,
        role=role,
        member_count=member_count,
        created_at=household.created_at,
    )


def _invitation_out(db: Session, inv: HouseholdInvitation) -> InvitationOut:
    household = db.query(Household).filter(Household.id == inv.household_id).first()
    inviter = db.query(User).filter(User.id == inv.inviter_user_id).first()
    return InvitationOut(
        id=inv.id,
        household_id=inv.household_id,
        household_name=household.name if household else "",
        inviter_user_id=inv.inviter_user_id,
        inviter_username=inviter.username if inviter else "",
        invitee_user_id=inv.invitee_user_id,
        status=inv.status,
        created_at=inv.created_at,
        responded_at=inv.responded_at,
    )


# ----- Endpoints -------------------------------------------------------------

@router.post("", response_model=HouseholdSummary, status_code=status.HTTP_201_CREATED)
async def create_household(
    body: HouseholdCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    household = Household(name=body.name.strip(), created_by_user_id=current_user.id)
    db.add(household)
    db.flush()

    membership = HouseholdMember(
        household_id=household.id,
        user_id=current_user.id,
        role=HouseholdRole.ADMIN,
    )
    db.add(membership)
    db.commit()
    db.refresh(household)

    return _household_summary(db, household, HouseholdRole.ADMIN)


@router.get("", response_model=list[HouseholdSummary])
async def list_my_households(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(Household, HouseholdMember.role)
        .join(HouseholdMember, HouseholdMember.household_id == Household.id)
        .filter(HouseholdMember.user_id == current_user.id)
        .order_by(Household.created_at.desc())
        .all()
    )
    return [_household_summary(db, h, role) for h, role in rows]


@router.get("/invitations/received", response_model=list[InvitationOut])
async def list_received_invitations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    invs = (
        db.query(HouseholdInvitation)
        .filter(
            HouseholdInvitation.invitee_user_id == current_user.id,
            HouseholdInvitation.status == InvitationStatus.PENDING,
        )
        .order_by(HouseholdInvitation.created_at.desc())
        .all()
    )
    return [_invitation_out(db, inv) for inv in invs]


@router.post("/invitations/{invitation_id}/accept", response_model=HouseholdSummary)
async def accept_invitation(
    invitation_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    inv = db.query(HouseholdInvitation).filter(HouseholdInvitation.id == invitation_id).first()
    if inv is None or inv.invitee_user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Invitation not found")
    if inv.status != InvitationStatus.PENDING:
        raise HTTPException(status_code=400, detail=f"Invitation already {inv.status.value}")

    inv.status = InvitationStatus.ACCEPTED
    inv.responded_at = datetime.now(tz=timezone.utc)

    if household_service.get_membership(db, inv.household_id, current_user.id) is None:
        db.add(HouseholdMember(
            household_id=inv.household_id,
            user_id=current_user.id,
            role=HouseholdRole.MEMBER,
        ))

    db.commit()
    household = db.query(Household).filter(Household.id == inv.household_id).first()
    return _household_summary(db, household, HouseholdRole.MEMBER)


@router.post("/invitations/{invitation_id}/decline", response_model=InvitationOut)
async def decline_invitation(
    invitation_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    inv = db.query(HouseholdInvitation).filter(HouseholdInvitation.id == invitation_id).first()
    if inv is None or inv.invitee_user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Invitation not found")
    if inv.status != InvitationStatus.PENDING:
        raise HTTPException(status_code=400, detail=f"Invitation already {inv.status.value}")

    inv.status = InvitationStatus.DECLINED
    inv.responded_at = datetime.now(tz=timezone.utc)
    db.commit()
    db.refresh(inv)
    return _invitation_out(db, inv)


@router.get("/{household_id}", response_model=HouseholdDetail)
async def get_household(
    household_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    membership = household_service.assert_member(db, household_id, current_user.id)
    household = db.query(Household).filter(Household.id == household_id).first()

    member_rows = (
        db.query(HouseholdMember, User)
        .join(User, User.id == HouseholdMember.user_id)
        .filter(HouseholdMember.household_id == household_id)
        .order_by(HouseholdMember.joined_at.asc())
        .all()
    )
    members = [
        MemberOut(
            user_id=u.id,
            username=u.username,
            email=u.email,
            role=m.role,
            joined_at=m.joined_at,
        )
        for m, u in member_rows
    ]

    return HouseholdDetail(
        id=household.id,
        name=household.name,
        role=membership.role,
        members=members,
        created_at=household.created_at,
    )


@router.patch("/{household_id}", response_model=HouseholdSummary)
async def rename_household(
    household_id: int,
    body: HouseholdRename,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    household_service.assert_admin(db, household_id, current_user.id)
    household = db.query(Household).filter(Household.id == household_id).first()
    household.name = body.name.strip()
    db.commit()
    db.refresh(household)
    return _household_summary(db, household, HouseholdRole.ADMIN)


@router.delete("/{household_id}")
async def delete_household(
    household_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    household_service.assert_admin(db, household_id, current_user.id)
    household = db.query(Household).filter(Household.id == household_id).first()
    db.delete(household)
    db.commit()
    return {"message": "Household deleted"}


@router.post("/{household_id}/invitations", response_model=InvitationOut, status_code=status.HTTP_201_CREATED)
async def invite_to_household(
    household_id: int,
    body: InviteRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    household_service.assert_admin(db, household_id, current_user.id)

    needle = body.email_or_username.strip().lower()
    invitee = (
        db.query(User)
        .filter(or_(sa_func.lower(User.email) == needle, sa_func.lower(User.username) == needle))
        .first()
    )
    if invitee is None:
        raise HTTPException(status_code=404, detail="No user with that email or username")
    if invitee.id == current_user.id:
        raise HTTPException(status_code=400, detail="You're already in this household")

    if household_service.get_membership(db, household_id, invitee.id) is not None:
        raise HTTPException(status_code=400, detail="User is already a member of this household")

    existing = (
        db.query(HouseholdInvitation)
        .filter(
            HouseholdInvitation.household_id == household_id,
            HouseholdInvitation.invitee_user_id == invitee.id,
            HouseholdInvitation.status == InvitationStatus.PENDING,
        )
        .first()
    )
    if existing is not None:
        raise HTTPException(status_code=400, detail="A pending invitation already exists for this user")

    inv = HouseholdInvitation(
        household_id=household_id,
        inviter_user_id=current_user.id,
        invitee_user_id=invitee.id,
        status=InvitationStatus.PENDING,
    )
    db.add(inv)
    db.commit()
    db.refresh(inv)
    return _invitation_out(db, inv)


@router.get("/{household_id}/invitations", response_model=list[InvitationOut])
async def list_household_invitations(
    household_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    household_service.assert_member(db, household_id, current_user.id)
    invs = (
        db.query(HouseholdInvitation)
        .filter(
            HouseholdInvitation.household_id == household_id,
            HouseholdInvitation.status == InvitationStatus.PENDING,
        )
        .order_by(HouseholdInvitation.created_at.desc())
        .all()
    )
    return [_invitation_out(db, inv) for inv in invs]


@router.delete("/{household_id}/invitations/{invitation_id}")
async def cancel_invitation(
    household_id: int,
    invitation_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    household_service.assert_admin(db, household_id, current_user.id)
    inv = (
        db.query(HouseholdInvitation)
        .filter(
            HouseholdInvitation.id == invitation_id,
            HouseholdInvitation.household_id == household_id,
        )
        .first()
    )
    if inv is None:
        raise HTTPException(status_code=404, detail="Invitation not found")
    if inv.status != InvitationStatus.PENDING:
        raise HTTPException(status_code=400, detail=f"Invitation already {inv.status.value}")
    inv.status = InvitationStatus.CANCELLED
    inv.responded_at = datetime.now(tz=timezone.utc)
    db.commit()
    return {"message": "Invitation cancelled"}


@router.delete("/{household_id}/members/{user_id}")
async def remove_or_leave_member(
    household_id: int,
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Admins can remove anyone; members can remove themselves (leave)."""
    target = household_service.get_membership(db, household_id, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Member not found")

    is_self = user_id == current_user.id
    if not is_self:
        household_service.assert_admin(db, household_id, current_user.id)
    else:
        household_service.assert_member(db, household_id, current_user.id)

    if target.role == HouseholdRole.ADMIN:
        other_admins = (
            db.query(sa_func.count(HouseholdMember.id))
            .filter(
                HouseholdMember.household_id == household_id,
                HouseholdMember.role == HouseholdRole.ADMIN,
                HouseholdMember.user_id != user_id,
            )
            .scalar()
        )
        other_members_total = (
            db.query(sa_func.count(HouseholdMember.id))
            .filter(
                HouseholdMember.household_id == household_id,
                HouseholdMember.user_id != user_id,
            )
            .scalar()
        )
        if other_members_total > 0 and other_admins == 0:
            raise HTTPException(
                status_code=400,
                detail="Cannot remove the last admin while other members exist. Promote another member first.",
            )

    db.delete(target)

    remaining = (
        db.query(sa_func.count(HouseholdMember.id))
        .filter(HouseholdMember.household_id == household_id)
        .scalar()
    )
    if remaining == 0:
        household = db.query(Household).filter(Household.id == household_id).first()
        if household is not None:
            db.delete(household)

    db.commit()
    return {"message": "Member removed" if not is_self else "Left household"}
