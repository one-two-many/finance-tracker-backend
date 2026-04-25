import enum
from sqlalchemy import Column, Integer, DateTime, ForeignKey, UniqueConstraint, Enum as SQLEnum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class HouseholdRole(str, enum.Enum):
    ADMIN = "admin"
    MEMBER = "member"


class HouseholdMember(Base):
    __tablename__ = "household_members"
    __table_args__ = (
        UniqueConstraint("household_id", "user_id", name="household_members_household_id_user_id_key"),
    )

    id = Column(Integer, primary_key=True, index=True)
    household_id = Column(Integer, ForeignKey("households.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    role = Column(
        SQLEnum(
            HouseholdRole,
            name="household_role",
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        nullable=False,
        default=HouseholdRole.MEMBER,
    )
    joined_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    household = relationship("Household", back_populates="members")
    user = relationship("User", back_populates="household_memberships")
