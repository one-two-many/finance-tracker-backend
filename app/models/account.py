from sqlalchemy import Column, Integer, String, Numeric, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base
import enum


class AccountType(str, enum.Enum):
    CHECKING = "checking"
    SAVINGS = "savings"
    CREDIT_CARD = "credit_card"
    INVESTMENT = "investment"
    CASH = "cash"
    OTHER = "other"


class Account(Base):
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    account_type = Column(SQLEnum(AccountType), nullable=False)
    currency = Column(String(3), default="USD")
    initial_balance = Column(Numeric(10, 2), default=0.0)
    current_balance = Column(Numeric(10, 2), default=0.0)

    # Bank information for import matching
    bank_name = Column(String(100), nullable=True)
    account_number_last4 = Column(String(4), nullable=True)
    default_parser = Column(String(50), nullable=True)  # Linked CSV parser (e.g., "amex", "discover_bank")

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="accounts")
    transactions = relationship("Transaction", foreign_keys="[Transaction.account_id]", back_populates="account", cascade="all, delete-orphan")
