"""
Import session model for tracking CSV imports.
"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base
import enum


class ImportStatus(str, enum.Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"


class ImportSession(Base):
    """
    Tracks CSV import sessions for review and audit purposes.
    """
    __tablename__ = "import_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False, index=True)

    filename = Column(String(255), nullable=True)
    parser_type = Column(String(50), nullable=False)
    status = Column(SQLEnum(ImportStatus), default=ImportStatus.COMPLETED)

    # Statistics
    total_rows = Column(Integer, default=0)
    created_count = Column(Integer, default=0)
    skipped_count = Column(Integer, default=0)
    error_count = Column(Integer, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    user = relationship("User", back_populates="import_sessions")
    account = relationship("Account")
    transactions = relationship("Transaction", back_populates="import_session")
