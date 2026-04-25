import enum
from sqlalchemy import Column, Integer, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class InvitationStatus(str, enum.Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    CANCELLED = "cancelled"


class HouseholdInvitation(Base):
    __tablename__ = "household_invitations"

    id = Column(Integer, primary_key=True, index=True)
    household_id = Column(Integer, ForeignKey("households.id"), nullable=False)
    inviter_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    invitee_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    status = Column(
        SQLEnum(
            InvitationStatus,
            name="invitation_status",
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        nullable=False,
        default=InvitationStatus.PENDING,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    responded_at = Column(DateTime(timezone=True))

    household = relationship("Household", back_populates="invitations")
    inviter = relationship("User", foreign_keys=[inviter_user_id], back_populates="sent_invitations")
    invitee = relationship("User", foreign_keys=[invitee_user_id], back_populates="received_invitations")
