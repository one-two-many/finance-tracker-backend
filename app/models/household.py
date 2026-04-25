from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class Household(Base):
    __tablename__ = "households"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    members = relationship(
        "HouseholdMember",
        back_populates="household",
        cascade="all, delete-orphan",
    )
    invitations = relationship(
        "HouseholdInvitation",
        back_populates="household",
        cascade="all, delete-orphan",
    )
    accounts = relationship(
        "Account",
        back_populates="household",
        cascade="all, delete-orphan",
    )
