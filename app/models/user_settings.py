from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base
from cryptography.fernet import Fernet
from app.core.config import settings
import base64
import hashlib
from typing import Optional


class UserSettings(Base):
    """
    User settings model for storing preferences and encrypted API credentials.

    Uses Fernet symmetric encryption for API keys. The encryption key is derived
    from the application's SECRET_KEY to ensure keys are encrypted at rest.
    """
    __tablename__ = "user_settings"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)

    # Encrypted fields (stored with _ prefix, accessed via properties)
    _splitwise_api_key = Column("splitwise_api_key", String(500), nullable=True)
    splitwise_is_active = Column(Boolean, default=False)
    splitwise_last_verified_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="settings")

    def _get_cipher(self) -> Fernet:
        """
        Create Fernet cipher from SECRET_KEY.

        Derives a valid 32-byte Fernet key from the application's SECRET_KEY
        using SHA256 hashing and base64 URL-safe encoding.
        """
        key = base64.urlsafe_b64encode(
            hashlib.sha256(settings.SECRET_KEY.encode()).digest()
        )
        return Fernet(key)

    @property
    def splitwise_api_key(self) -> Optional[str]:
        """Decrypt and return Splitwise API key."""
        if not self._splitwise_api_key:
            return None
        try:
            return self._get_cipher().decrypt(self._splitwise_api_key.encode()).decode()
        except Exception:
            # If decryption fails, return None (corrupted or invalid key)
            return None

    @splitwise_api_key.setter
    def splitwise_api_key(self, value: Optional[str]):
        """Encrypt and store Splitwise API key."""
        if not value:
            self._splitwise_api_key = None
        else:
            self._splitwise_api_key = self._get_cipher().encrypt(value.encode()).decode()
