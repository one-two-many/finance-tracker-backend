"""
Bank parser template model for custom CSV formats.
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class BankParserTemplate(Base):
    """
    Custom parser templates for unsupported bank CSV formats.
    Users can define their own column mappings.
    """
    __tablename__ = "bank_parser_templates"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    bank_name = Column(String(100), nullable=False)
    parser_type = Column(String(50), nullable=False)  # 'credit_card' or 'bank_account'

    # JSON structure: {"date": "column_name", "amount": "column_name", ...}
    column_mapping = Column(JSON, nullable=False)
    date_format = Column(String(50), nullable=True)  # e.g., "%m/%d/%Y"

    is_default = Column(Boolean, default=False)  # System-provided template
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    user = relationship("User", back_populates="parser_templates")
