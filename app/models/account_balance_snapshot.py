"""
Account Balance Snapshot Model

Tracks account balances at specific points in time (typically month start/end).
Used for net worth calculations and balance history tracking.
"""

from sqlalchemy import Column, Integer, Numeric, DateTime, ForeignKey, Date, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class AccountBalanceSnapshot(Base):
    __tablename__ = "account_balance_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False, index=True)
    import_session_id = Column(Integer, ForeignKey("import_sessions.id"), nullable=True, index=True)

    # Balance information
    balance = Column(Numeric(12, 2), nullable=False)
    snapshot_date = Column(Date, nullable=False, index=True)
    snapshot_type = Column(String, nullable=False)  # 'start', 'end', 'manual'

    # Period information (for monthly snapshots)
    period_year = Column(Integer, nullable=True, index=True)
    period_month = Column(Integer, nullable=True, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    user = relationship("User")
    account = relationship("Account")
    import_session = relationship("ImportSession")
