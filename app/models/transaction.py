from sqlalchemy import Column, Integer, String, Numeric, DateTime, ForeignKey, Enum as SQLEnum, Text, JSON, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base
import enum


class TransactionType(str, enum.Enum):
    INCOME = "income"
    EXPENSE = "expense"
    TRANSFER = "transfer"


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False, index=True)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True, index=True)

    transaction_type = Column(SQLEnum(TransactionType), nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    description = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    transaction_date = Column(DateTime(timezone=True), nullable=False, index=True)

    # For transfers
    transfer_to_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)

    # Import tracking
    import_session_id = Column(Integer, ForeignKey("import_sessions.id"), nullable=True, index=True)
    raw_data = Column(JSON, nullable=True)  # Original CSV row data

    # Splitwise
    splitwise_split = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="transactions")
    account = relationship("Account", foreign_keys=[account_id], back_populates="transactions")
    category = relationship("Category", back_populates="transactions")
    import_session = relationship("ImportSession", back_populates="transactions")
