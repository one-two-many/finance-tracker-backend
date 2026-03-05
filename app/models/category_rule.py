"""
Category rule model for auto-categorization.
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base
import enum


class PatternType(str, enum.Enum):
    KEYWORD = "keyword"
    EXACT = "exact"
    REGEX = "regex"


class CategoryRule(Base):
    """
    Rules for automatic transaction categorization based on description patterns.
    """
    __tablename__ = "category_rules"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=False)

    pattern = Column(String(255), nullable=False)
    pattern_type = Column(SQLEnum(PatternType), default=PatternType.KEYWORD)
    priority = Column(Integer, default=0)  # Higher priority rules checked first
    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    user = relationship("User", back_populates="category_rules")
    category = relationship("Category", back_populates="rules")
